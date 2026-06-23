"""ServerLevel -- the server-authoritative enemy brain (Stage C / server-auth).

DIRECTION CHANGE (see the multiplayer plan, "C3 / server-authoritative"): the
server stops being a dumb relay and becomes the authority for enemies. It runs
the **real** ``Spawner`` + ``CombatUnit`` simulation **headless** (under dummy
SDL), driven by a server-side combat-context that resolves damage/XP/loot
against server state instead of a rendered ``Level4``.

Why this is safe and faithful: the server is the **sole** simulator of enemies
(both clients render them as ``EnemyPuppet``s), so there is no second sim to
diverge from -- the server runs the enemy AI/movement/collision EXACTLY as
singleplayer does, just without a display. This deliberately evolves the old
"the server never instantiates CombatUnit" boundary (Server/common.py) that
Stage B started loosening (geometry only); the player model there stays minimal.

CS1 scope (this file's first cut): spawn enemies + per-frame ``tick`` that makes
them acquire a player target and move/attack -- proven headless by
``tests/test_server_enemy_sim.py``. Damage->client relay, health sync, and
death/loot events land in CS3-CS5.
"""

import os
import random
import sys

# Headless before pygame/combat_unit import: the real sim loads monster art via
# convert_alpha (needs an SDL display surface) -- dummy drivers make that work
# with no real window. server.py sets these too; setdefault keeps us idempotent.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_CODE_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Code"))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

import pygame  # noqa: E402

# The REAL sim, imported unchanged and run headless (the whole point of the
# pivot -- reuse, not a fork). combat_unit chdir's to Code/ on import so its
# "../Graphics/..." asset paths resolve.
from Settings import (  # noqa: E402
    ENTITY_BROADPHASE_BACKEND,
    ENTITY_BROADPHASE_GRID_CELL_SIZE,
)
from Spawner import Spawner  # noqa: E402
from Interaction import InteractionResolver, InteractionContext  # noqa: E402
from QuadTree import QuadTree, QuadTreeManager  # noqa: E402
from hashRect import HashableRect  # noqa: E402
from benchmark_broadphase import MovingEntityBroadphaseAdapter  # noqa: E402
from loot_table import resolve_loot_table, resolve_gold_drop  # noqa: E402
from network.protocol import (  # noqa: E402
    MSG_ENEMY_DIED,
    MSG_HIT_PLAYER,
    MSG_ITEM_DROPPED,
    MSG_ITEM_REMOVED,
)


# CS4b: geometric projectile constants. Matches the client's per-frame step
# (ParticleEffect moves direction*12 per frame) at the 60Hz server tick, and its
# total travel distance, so server projectiles behave like the singleplayer ones.
_PROJECTILE_SPEED = 12.0        # px per tick (== distance advanced per tick)
_PROJECTILE_MAX_DISTANCE = 1000.0
_PROJECTILE_SIZE = 24           # collision box side (px)


def ensure_headless_display():
    """Make the headless pygame env CombatUnit construction needs:
    - a live display surface (convert_alpha when loading monster art needs one;
      under SDL_VIDEODRIVER=dummy it's a no-op offscreen surface -- no window);
    - an initialized mixer (CombatUnit loads hit/attack/death Sounds in __init__;
      under SDL_AUDIODRIVER=dummy these are silent no-ops).
    Idempotent: only initializes what's missing, so the real server (which never
    calls pygame.init()) and the test suite (which does) both work."""
    if not pygame.display.get_init():
        pygame.display.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((1, 1))
    if not pygame.mixer.get_init():
        try:
            pygame.mixer.init()
        except pygame.error:
            pass  # no audio device even under dummy -- Sound() would still fail,
            # but that's an environment problem, not something we can paper over.


class _NoopAnimationPlayer:
    """The sim only calls animation_player for VISUAL particles (death FX, hurt
    particles). The server never renders, so these are no-ops; the actual
    death-FX *event* is relayed to clients via ServerLevel.trigger_death_particles."""

    def create_particles(self, *args, **kwargs):
        return None


class _ServerLayout:
    """Stands in for ``Level4.layout_manager`` for what the enemy sim reads:
    the two sprite groups it joins, the obstacle quad tree it collides against,
    and the entity quad tree it aggros through. No display/surfaces."""

    def __init__(self, world_w, world_h):
        self.csv_layout_width = world_w
        self.csv_layout_height = world_h
        self.visible_sprites = pygame.sprite.Group()
        self.obstacle_sprites = pygame.sprite.Group()
        world_rect = pygame.Rect(0, 0, world_w, world_h)
        # Real obstacle quad tree (empty until obstacles are uploaded -- CS later;
        # CS1 runs on open ground). The manager mirrors tmx_layout_manager's setup.
        self.obstacle_quad_tree = QuadTree(
            items=[], depth=8, bounding_rect=world_rect, manager=QuadTreeManager()
        )
        # Real moving-entity broadphase: enemies + player targets register here so
        # ``select_hostile_target`` finds them (same class the client uses).
        self.entity_quad_tree = MovingEntityBroadphaseAdapter(
            world_rect=world_rect,
            backend=ENTITY_BROADPHASE_BACKEND,
            grid_cell_size=ENTITY_BROADPHASE_GRID_CELL_SIZE,
        )

    def add_obstacle_sprite_to_quad_tree(self, obstacle_sprite, alive=True, remove_existing=True):
        # Same name/shape Level4 exposes -- this is what combat_context's
        # "update_quad_tree" callback points at, so enemies self-register on move.
        self.entity_quad_tree.insert(obstacle_sprite, alive=alive, remove_existing=remove_existing)


class ServerPlayerTarget:
    """Server-side aggro/damage target for a networked player.

    Holds ONLY what the enemy sim reads off a target: ``rect``/``team_id``/
    ``health`` (+ the ``receive_interaction`` gate the resolver calls). The
    server does NOT own player health -- the owning client does (it applies real
    i-frames/death locally). So incoming damage is just **recorded** here for
    relay to that client (CS4); the authoritative ``health`` is whatever the
    client last reported (``update``), which is what gates aggro (dead -> ignored).
    """

    # _id key for the entity map / HashableRect is the player_id STRING, so it
    # can never collide with the integer Entity.id of an enemy.
    def __init__(self, player_id, x, y, health=100, max_health=100, hitbox_size=(50, 50)):
        self.player_id = player_id
        self.id = player_id
        self.team_id = "player"
        self.rect = pygame.Rect(0, 0, hitbox_size[0], hitbox_size[1])
        self.rect.center = (x, y)
        self.hitbox = self.rect
        self.health = health
        self.max_health = max_health
        self.vulnerable = True
        self.is_dead = False
        # [(amount, attack_type), ...] -- drained by the server each tick to relay
        # MSG_HIT_PLAYER to the owning client (CS4). Empty in CS1 unless a melee lands.
        self.incoming_hits = []

    def set_position(self, x, y):
        self.rect.center = (int(x), int(y))

    def can_receive_interaction(self, ctx: InteractionContext):
        if ctx.kind != "damage":
            return False
        return ctx.source_team != self.team_id

    def receive_interaction(self, ctx: InteractionContext):
        if ctx.kind != "damage":
            return
        amount = ctx.amount
        if amount is None:
            src = ctx.source
            if src is not None and hasattr(src, "get_full_weapon_damage") and hasattr(src, "get_full_magic_damage"):
                amount = src.get_full_weapon_damage() if ctx.attack_type == "weapon" else src.get_full_magic_damage()
        if amount is None:
            return
        # Record, don't apply: the owning client is authoritative for its player's
        # health (its own i-frames/death). The server relays this hit (CS4).
        self.incoming_hits.append((amount, ctx.attack_type))


class ServerLevel:
    """Drives the real enemy sim headless. Mirrors the small set of ``Level4``
    attributes + ``combat_context`` callbacks that ``Spawner``/``CombatUnit`` read
    (see Spawner.generate_combat_context)."""

    def __init__(self, world_w=20000, world_h=20000, obstacle_quad_tree=None):
        ensure_headless_display()
        self.layout_manager = _ServerLayout(world_w, world_h)
        # CS2: reuse the obstacle QuadTree the server already built from the
        # client's geometry upload (Stage B), so server enemies collide against
        # the real map walls instead of walking through them. None -> open ground.
        if obstacle_quad_tree is not None:
            self.layout_manager.obstacle_quad_tree = obstacle_quad_tree
        self.attackable_sprites = pygame.sprite.Group()
        self.interaction_resolver = InteractionResolver()
        self.animation_player = _NoopAnimationPlayer()
        self.player_targets = {}  # player_id -> ServerPlayerTarget
        self.player = None        # combat_context "default_target" fallback
        self.global_spawn_limits = None
        self.frame_number = 0
        # CS5a: enemies that died THIS tick, captured for the enemy_died broadcast
        # (carries id/pos/monster/exp). Death FX + XP are applied on each client.
        self.pending_deaths = []    # [{id, x, y, monster, exp}, ...]
        # CS5b: server-owned shared loot. The server rolls drops on death, assigns
        # a stable drop_id, and arbitrates pickups (first claim wins). The registry
        # holds outstanding drops; pending_item_drops queues item_dropped events.
        self.dropped_items = {}     # drop_id -> {item_id, x, y[, gold]}
        self._next_drop_id = 0
        self.pending_item_drops = []
        # CS4b: live geometric projectiles fired by ranged enemies. Each is a
        # plain dict {x,y,vx,vy,damage,attack_type,traveled,source_team}; they
        # travel straight and record a hit on an overlapping player target
        # (-> hit_player via drain_player_hits). No display-coupled ParticleEffect.
        self.projectiles = []
        # The real Spawner, pointed at THIS level. fire_projectile must exist first.
        self.spawner = Spawner(self, persistent_enemy_data={}, fire_projectile=self.fire_projectile)
        # The server owns + syncs ENEMIES, not NEUTRALs (NeutralCharacter has its
        # own AI/render that isn't relayed yet). Make neutral spawning a safe no-op
        # so a mixed spawn area's neutral roll never crashes the headless sim.
        self.spawner.spawn_neutral = lambda *args, **kwargs: None

    # ---- combat_context callbacks (faithful ports of Level4's) ----
    def emit_enemy_melee_hit(self, enemy, target, attack):
        """Resolve an enemy melee hit through the REAL resolver (== Level4's)."""
        amount = None
        attack_type = "melee"
        if isinstance(attack, dict):
            amount = attack.get("damage")
            attack_type = attack.get("type", "melee")
        source_team = getattr(enemy, "team_id", "enemy")
        target_team = getattr(target, "team_id", None)
        if not self.interaction_resolver.can_potentially_affect(
            source_team=source_team, target_team=target_team, kind="damage"
        ):
            return
        ctx = InteractionContext(
            kind="damage",
            source_kind="enemy_melee",
            source=enemy,
            owner=enemy,
            source_team=source_team,
            target=target,
            amount=amount,
            attack_type=attack_type,
            tags={"enemy_melee"},
        )
        self.interaction_resolver.apply(ctx)

    def damage_player(self, amount, attack_type=None):
        # Legacy direct-damage path; the melee strategy uses emit_enemy_melee_hit.
        # Present because some combat_configs request the "damage_player" key.
        return None

    def trigger_death_particles(self, pos, particle_type):
        # The death FX is relayed to clients via the enemy_died event (CS5a,
        # captured in tick from the dying enemy), not rendered server-side. No-op.
        return None

    def add_exp(self, amount):
        # Co-op XP is awarded on each client via the enemy_died event (the exp
        # value rides in it). Nothing to award server-side. No-op.
        return None

    def fire_projectile(self, enemy_pos, target_pos, projectile_type, groups,
                        owner=None, source_team=None, amount=None):
        """CS4b: spawn a geometric server-side projectile (rect + velocity +
        damage) aimed at the target. It travels straight and, on overlapping a
        player target, records a hit (-> hit_player). `amount` is the ranged
        attack's base damage (CombatStrategy passes attack['damage'])."""
        direction = pygame.math.Vector2(target_pos[0] - enemy_pos[0],
                                        target_pos[1] - enemy_pos[1])
        if direction.length_squared() == 0:
            return None
        direction = direction.normalize()
        self.projectiles.append({
            "x": float(enemy_pos[0]),
            "y": float(enemy_pos[1]),
            "vx": direction.x * _PROJECTILE_SPEED,
            "vy": direction.y * _PROJECTILE_SPEED,
            "damage": amount,
            "attack_type": "magic",
            "traveled": 0.0,
            "source_team": source_team or getattr(owner, "team_id", "enemy"),
        })
        return None

    def _tick_projectiles(self):
        """CS4b: advance each live projectile one tick; on overlapping an
        opposing-team player target, record the hit (consumed) -> hit_player.
        Expire past the max travel distance. No obstacle collision (straight
        flight) -- a reasonable first cut; the enemy is visibly attacking."""
        if not self.projectiles:
            return
        half = _PROJECTILE_SIZE // 2
        targets = list(self.player_targets.values())
        alive = []
        for p in self.projectiles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["traveled"] += _PROJECTILE_SPEED
            rect = pygame.Rect(int(p["x"]) - half, int(p["y"]) - half,
                               _PROJECTILE_SIZE, _PROJECTILE_SIZE)
            consumed = False
            for t in targets:
                if t.team_id == p["source_team"]:
                    continue  # no friendly fire
                if t.health > 0 and rect.colliderect(t.rect):
                    if p["damage"] is not None:
                        t.incoming_hits.append((p["damage"], p["attack_type"]))
                    consumed = True
                    break
            if not consumed and p["traveled"] < _PROJECTILE_MAX_DISTANCE:
                alive.append(p)
        self.projectiles = alive

    def redirect_projectile_callback(self, projectile_id, new_direction):
        return None

    # ---- player targets (positions/health come from client reports) ----
    def add_player_target(self, player_id, x, y, health=100, max_health=100):
        target = ServerPlayerTarget(player_id, x, y, health, max_health)
        self.player_targets[player_id] = target
        if self.player is None:
            self.player = target
        return target

    def update_player_target(self, player_id, x, y, health=None):
        target = self.player_targets.get(player_id)
        if target is None:
            return None
        target.set_position(x, y)
        if health is not None:
            target.health = health
        return target

    def remove_player_target(self, player_id):
        target = self.player_targets.pop(player_id, None)
        if target is not None:
            self.layout_manager.entity_quad_tree.remove(target.id)
        if self.player is target:
            self.player = next(iter(self.player_targets.values()), None)
        return target

    def spawn_enemy(self, config, pos=None):
        # Spawner.spawn_enemy appends to spawner.enemies but returns None (the
        # game ignores its return) -- hand back the actual unit we just made (or
        # None if the spawn was rejected, e.g. global spawn limits).
        before = len(self.spawner.enemies)
        self.spawner.spawn_enemy(config, pos)
        if len(self.spawner.enemies) > before:
            return self.spawner.enemies[-1]
        return None

    def register_spawn_areas(self, areas):
        """CS-fix: register the map's ENEMY spawn areas so the server spawns the
        level's proximity/timed enemies. Most levels (incl. the MP level) spawn
        their enemies via these areas, NOT placed entities. Pure-neutral areas are
        skipped -- the server doesn't own/sync neutrals yet."""
        for area in areas or []:
            config = area.get("config") or {}
            if not config.get("enemy_spawn_weights"):
                continue  # neutral-only area
            self.spawner.add_spawn_area(
                area.get("matrix"), config, area.get("object_info") or {},
            )

    def live_enemies(self):
        return [e for e in self.spawner.enemies if getattr(e, "health", 0) > 0 and e.alive()]

    def apply_enemy_hit(self, enemy_id, amount, attack_type):
        """CS3: apply a client's relayed attack to the authoritative enemy.

        The client resolved the amount from ITS player's stats (the server has no
        player combat stats) and relayed the number; we route it through the REAL
        InteractionResolver so the enemy's i-frames + retaliation behave exactly
        as in singleplayer. Health/death then ride the CS2 enemy broadcast back to
        every client (on death the enemy drops from the list -> puppets killed).
        Returns True if an enemy was hit."""
        if enemy_id is None or amount is None:
            return False
        enemy = next((e for e in self.spawner.enemies if e.id == enemy_id), None)
        if enemy is None:
            return False  # already dead/despawned
        ctx = InteractionContext(
            kind="damage",
            source_kind="player_attack",
            source=None,            # the client's stats are already baked into amount
            source_team="player",
            target=enemy,
            amount=amount,
            attack_type=attack_type,
        )
        self.interaction_resolver.apply(ctx)
        return True

    def drain_player_hits(self):
        """CS4: collect + clear the enemy->player melee/projectile hits the sim
        recorded on each ServerPlayerTarget this tick, as `hit_player` broadcast
        events. The victim's client applies the damage to its REAL player (its own
        i-frames/death); the server never owns player health (it only tracks the
        relayed value to gate aggro)."""
        events = []
        for target in self.player_targets.values():
            if not target.incoming_hits:
                continue
            for amount, attack_type in target.incoming_hits:
                events.append({
                    "type": MSG_HIT_PLAYER,
                    "target_player_id": target.player_id,
                    "amount": amount,
                    "attack_type": attack_type,
                })
            target.incoming_hits.clear()
        return events

    def gather_enemy_relay(self):
        """Snapshot each live enemy's render state for the wire. IDENTICAL shape
        to the old host-side Level4._gather_enemy_relay, so clients' existing
        _reconcile_enemy_puppets consumes it unchanged: {id,type,x,y,status,dir,health}."""
        out = []
        for e in self.live_enemies():
            monster_name = getattr(e, "monster_name", None)
            if monster_name is None:
                continue
            out.append({
                "id": e.id,
                "type": monster_name,
                "x": e.rect.centerx,
                "y": e.rect.centery,
                "status": getattr(e, "status", "idle"),
                "dir": e.get_direction_as_string() if hasattr(e, "get_direction_as_string") else "right",
                "health": getattr(e, "health", 0),
            })
        return out

    def sync_player_targets(self, players):
        """Reconcile the aggro/damage targets to the current players. ``players``
        is an iterable of dicts {player_id, x, y[, health]} (the server's live
        player states). Adds joiners, updates moved players, drops the departed.
        Health defaults to alive (100) until the health relay lands (CS4)."""
        seen = set()
        for p in players:
            pid = p["player_id"]
            seen.add(pid)
            health = p.get("health")
            if pid in self.player_targets:
                self.update_player_target(pid, p["x"], p["y"], health)
            else:
                self.add_player_target(pid, p["x"], p["y"], health=health if health is not None else 100)
        for pid in list(self.player_targets):
            if pid not in seen:
                self.remove_player_target(pid)

    def tick(self, dt):
        """One authoritative sim step: register targets, let every enemy decide
        (combat_update) then act (update == move/animate/death), prune the dead.
        Mirrors Level4's per-frame enemy_update sweep + update_parallel."""
        lm = self.layout_manager
        # CS-fix: run the map's enemy spawn areas (proximity/timed). This is how
        # the level actually populates enemies -- it has no placed enemies. Uses a
        # player target as the proximity reference (first one; co-op players are
        # usually together). dt drives the per-area spawn timers (real seconds).
        if self.spawner.spawn_areas and self.player_targets:
            ref_player = next(iter(self.player_targets.values()))
            self.spawner.handle_spawn_areas(ref_player, dt)

        # Keep each player target current in the entity tree (dead -> removed, so
        # enemies disengage). Their (x, y)/health come from client reports.
        for target in self.player_targets.values():
            lm.add_obstacle_sprite_to_quad_tree(
                HashableRect(target.rect, target.id),
                alive=(target.health > 0),
                remove_existing=True,
            )

        enemies = self.live_enemies()
        entity_id_map = {e.id: e for e in enemies}
        entity_id_map.update({t.id: t for t in self.player_targets.values()})

        # Decide (targeting/aggro/attack intent).
        for enemy in enemies:
            enemy.combat_update(
                quadtree=lm.entity_quad_tree,
                entity_id_map=entity_id_map,
                frame_number=self.frame_number,
            )
        # Act (move/animate/cooldowns/death). Same call the camera group makes.
        # Ranged enemies fire here via combat_context["fire_projectile"], which
        # appends to self.projectiles.
        for enemy in enemies:
            enemy.update(
                QuadTree=lm.obstacle_quad_tree,
                entity_quad_tree=lm.entity_quad_tree,
                dt=dt,
            )

        # CS4b: advance projectiles + resolve enemy->player hits.
        self._tick_projectiles()

        # CS5a: capture enemies that died this tick (check_death already kill()'d
        # them) for the enemy_died broadcast, then drop them from the sim.
        survivors = []
        for e in self.spawner.enemies:
            if getattr(e, "health", 0) > 0 and e.alive():
                survivors.append(e)
            else:
                self.pending_deaths.append({
                    "id": e.id,
                    "x": e.rect.centerx,
                    "y": e.rect.centery,
                    "monster": getattr(e, "monster_name", ""),
                    "exp": getattr(e, "exp", 0),
                })
                self._roll_and_register_drops(e)  # CS5b
        self.spawner.enemies = survivors
        self.frame_number += 1

    def _roll_and_register_drops(self, enemy):
        """CS5b: roll an enemy's loot (item_ids + gold) WITHOUT building display-
        coupled Item objects -- the server only needs item_id + position (+ gold
        amount) for the item_dropped event; each client recreates the visual.
        Mirrors ItemSpawner.drop_from_enemy's roll. Each drop gets a stable
        drop_id and is registered for pickup arbitration."""
        drop_info = getattr(enemy, "item_drop_info", None)
        if not drop_info:
            return
        x, y = enemy.rect.bottomright
        rolled = [{"item_id": item_id, "x": x, "y": y}
                  for item_id, _qty in resolve_loot_table(drop_info)]
        gold = resolve_gold_drop(drop_info, random)
        if gold and gold > 0:
            rolled.append({"item_id": "gold_coin", "x": x, "y": y, "gold": int(gold)})
        for drop in rolled:
            self._next_drop_id += 1
            drop_id = self._next_drop_id
            self.dropped_items[drop_id] = drop
            event = {"type": MSG_ITEM_DROPPED, "drop_id": drop_id,
                     "item_id": drop["item_id"], "x": drop["x"], "y": drop["y"]}
            if "gold" in drop:
                event["gold"] = drop["gold"]  # keep the rolled gold amount exact
            self.pending_item_drops.append(event)

    def drain_item_drops(self):
        """CS5b: collect + clear this tick's item_dropped events (server -> all)."""
        events = self.pending_item_drops
        self.pending_item_drops = []
        return events

    def arbitrate_pickup(self, drop_id, player_id):
        """CS5b: the first client to claim a shared drop wins. Remove it from the
        world and return an item_removed event awarding it to the requester; None
        if it's already gone (a losing double-claim -> the loser banks nothing)."""
        if drop_id not in self.dropped_items:
            return None
        del self.dropped_items[drop_id]
        return {"type": MSG_ITEM_REMOVED, "drop_id": drop_id, "to": player_id}

    def drain_deaths(self):
        """CS5a: collect + clear the enemies that died this tick as enemy_died
        broadcast events. Each client plays the death FX/sound, removes the
        puppet, and awards the (full, co-op) XP via the existing _handle_enemy_died."""
        events = [
            {"type": MSG_ENEMY_DIED, "id": d["id"], "x": d["x"], "y": d["y"],
             "monster": d["monster"], "exp": d["exp"]}
            for d in self.pending_deaths
        ]
        self.pending_deaths = []
        return events
