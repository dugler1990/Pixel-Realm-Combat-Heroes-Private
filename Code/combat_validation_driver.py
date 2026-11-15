"""Combat validation scenes, run in the benchmark arena with the mesh hero (combat_validation.py).

Each scene sets itself up, runs, decides PASS / FAIL (checked by numbers) or PROBE (for Douglas to
watch: the numbers are reported, not judged), then stays on screen for hold_seconds. The overlay says
what to look for. Enemies are placed by pixel around the hero; between scenes everything spawned is
removed and the hero is put back, unarmoured, in the middle.
"""
from __future__ import annotations

import copy
import math
import time

import pygame

import contact_debug
import Player as player_module
from abilities.leap_slam import ChargedLeapSlamAbility
from combat_validation_runtime import COMBAT_VALIDATION_RUNTIME as RUNTIME
from damage_data import attack
from Entity import knockback_scale
from hashRect import HashableRect
from Interaction import InteractionContext
from Settings import ability_data

ARCHER = "warrior_00"
FULL_PLATE = ("barb_fullplate_belt", "barb_fullplate_boot_l", "barb_fullplate_boot_r", "barb_fullplate_chest",
              "barb_fullplate_gauntlet_l", "barb_fullplate_gauntlet_r", "barb_fullplate_pants_l",
              "barb_fullplate_pants_r", "barb_fullplate_shoulder_l", "barb_fullplate_shoulder_r")


# --- helpers -------------------------------------------------------------------------------------

def spawn_at(level, monster, dx, dy):
    """A monster with its feet `dx, dy` px from the hero's feet."""
    enemy = level.spawner.spawn_enemy({"type": monster, "pos": (0, 0)})
    cx, cy = level.player.hitbox.midbottom
    enemy.hitbox.midbottom = (int(cx + dx), int(cy + dy))
    enemy.plant_sprite_on_hitbox()
    return enemy


def ring(level, monster, count, radius):
    return [spawn_at(level, monster, radius * math.cos(2 * math.pi * i / count),
                     radius * math.sin(2 * math.pi * i / count)) for i in range(count)]


def remove_enemies(level):
    for enemy in list(level.spawner.enemies):
        enemy.layout_callback_update_quad_tree(obstacle_sprite=HashableRect(enemy.rect, enemy.id),
                                               remove_existing=True, alive=False)
        enemy.kill()
    level.spawner.enemies.clear()
    for sprite in list(level.enemy_attack_sprites):
        sprite.kill()


def wear(level, item_ids):
    """Take everything off, then put these items on (real items from the item spawner)."""
    inv = level.player.inventory
    for slot in inv.body_slots():
        slot.clear()
    for item_id in item_ids:
        cfg = level.item_spawner.item_mapping.get(item_id)
        if cfg is None:
            raise KeyError(f"no item {item_id!r}")
        inv.wear(level.item_spawner.create_item(copy.deepcopy(cfg), [0, 0]))
    inv.sync_belt_from_waist()


class Scene:
    NAME = ""
    WATCH = ""              # one line: what Douglas should see
    SECONDS = 6.0           # how long it runs before it is decided (visible); headless runs FAST_SECONDS
    FAST_SECONDS = 4.0

    def __init__(self):
        self.t = 0.0
        self.lines = []

    def setup(self, level):
        pass

    def tick(self, level, dt):
        pass

    def decide(self, level):
        """(status, details): status 'pass' / 'fail' / 'probe'."""
        return "probe", ""

    def teardown(self, level):
        pass


class HitLog:
    """Every interaction applied to the hero while installed: (ctx, landed, kind), kind = what the hit
    met when it landed ("plate" / "skin", contact_debug.kind_of: his pose at that moment), and every
    arrow sprite that stopped."""

    def __init__(self, level):
        from Particles import ParticleEffect

        self.level = level
        self.hits = []
        self.regions = []
        self.stopped = []
        self._original = level.interaction_resolver.apply
        self._effect = ParticleEffect
        self._stop = ParticleEffect.stop
        hero = level.player
        log = self

        def apply(ctx):
            landed = log._original(ctx)
            if ctx.target is hero:
                kind = region = None
                if landed and ctx.contact is not None:
                    import body_regions
                    import defence_profile

                    spot = body_regions.hit_layers(hero, ctx.contact)
                    kind = "plate" if spot.piece else "skin"
                    name, side = defence_profile.SLOTS[spot.slot]
                    region = name + (f" {side}" if side else "")
                log.hits.append((ctx, landed, kind))
                log.regions.append((kind, region))
            return landed

        def stop(sprite):
            if getattr(sprite, "attack_def", None) is attack("arrow"):
                log.stopped.append(sprite)
            return log._stop(sprite)

        level.interaction_resolver.apply = apply
        ParticleEffect.stop = stop

    def remove(self):
        self.level.interaction_resolver.apply = self._original
        self._effect.stop = self._stop

    def arrows(self):
        return [(ctx, landed, kind) for ctx, landed, kind in self.hits if ctx.attack_def is attack("arrow")]


# --- scenes --------------------------------------------------------------------------------------

class KnockbackMass(Scene):
    NAME = "knockback_mass"
    WATCH = "a leap slam lands among a demon (400), a raccoon (80), a snake (20): lighter ones fly further"
    SECONDS = FAST_SECONDS = 2.0

    def setup(self, level):
        self.bodies = {"demon": spawn_at(level, "demon", -95, 0), "raccoon": spawn_at(level, "raccoon", 95, 0),
                       "tribey_snake": spawn_at(level, "tribey_snake", 0, 70)}
        self.moved = {}
        self.slammed = False

    def tick(self, level, dt):
        if not self.slammed and self.t > 0.6:
            before = {k: pygame.math.Vector2(e.hitbox.center) for k, e in self.bodies.items()}
            ChargedLeapSlamAbility("leap_slam", ability_data["leap_slam"])._resolve_landing_aoe(
                level.player, None, level.layout_manager.entity_quad_tree, {"charge_ratio": 1.0})
            self.moved = {k: before[k].distance_to(e.hitbox.center) for k, e in self.bodies.items()}
            self.slammed = True

    def decide(self, level):
        m = self.moved
        details = ", ".join(f"{k} moved {v:.0f} px" for k, v in m.items())
        ok = bool(m) and m["tribey_snake"] > m["raccoon"] > m["demon"]
        return ("pass" if ok else "fail"), details


class ArrowsStop(Scene):
    NAME = "arrows_stop"
    WATCH = "3 archers shoot the barb: every arrow that hits him stops there (none flies through)"
    SECONDS, FAST_SECONDS = 8.0, 6.0

    def setup(self, level):
        ring(level, ARCHER, 3, 180)
        self.log = HitLog(level)

    def decide(self, level):
        arrows = self.log.arrows()
        landed = sum(1 for _, ok, _ in arrows if ok)
        stopped = len(self.log.stopped)
        refused = len(arrows) - landed
        details = (f"{landed} arrows landed, {stopped} arrows stopped (each that lands must stop); "
                   f"{refused} refused by the hero (they fly on)")
        return ("pass" if landed and stopped == landed else "fail"), details

    def teardown(self, level):
        self.log.remove()


class PlateShove(Scene):
    NAME = "plate_shove"
    WATCH = "the same shove, bare then in full plate: plated he moves ~3/4 as far (worn weight 31)"
    SECONDS = FAST_SECONDS = 2.0

    def setup(self, level):
        self.results = []

    def _shove(self, level):
        hero = level.player
        start = pygame.math.Vector2(hero.hitbox.center)
        level.interaction_resolver.apply(InteractionContext(
            kind="impulse", source_kind="combat_validation", source_team="enemy_1", target=hero,
            impulse_x=64.0, impulse_y=0.0, attack_def=attack("demon_claw")))
        moved = start.distance_to(hero.hitbox.center)
        hero.hitbox.center = (int(start.x), int(start.y))
        hero.plant_sprite_on_hitbox()
        hero.velocity.update(0, 0)
        return moved, knockback_scale(hero)

    def tick(self, level, dt):
        if not self.results and self.t > 0.3:
            self.results.append(self._shove(level))
            wear(level, FULL_PLATE)
        elif len(self.results) == 1 and self.t > 1.0:
            self.results.append(self._shove(level))

    def decide(self, level):
        if len(self.results) < 2:
            return "fail", "shoves did not run"
        (bare, s_bare), (plated, s_plate) = self.results
        ratio, expect = plated / max(bare, 1e-6), s_plate / s_bare
        details = (f"bare {bare:.1f} px, plated {plated:.1f} px: {ratio:.2f} (expected {expect:.2f}, "
                   f"gear {level.player.gear_weight:g})")
        return ("pass" if abs(ratio - expect) <= 0.08 else "fail"), details


class ArrowsWhereDrawn(Scene):
    NAME = "arrows_where_drawn"
    WATCH = "8 archers round the plated barb; dots where arrows land: GREY on plate, RED on skin (his bare head)"
    SECONDS, FAST_SECONDS = 14.0, 6.0

    def setup(self, level):
        wear(level, FULL_PLATE)
        ring(level, ARCHER, 8, 185)
        self.log = HitLog(level)

    def _counts(self, hits):
        plate = sum(1 for _, _, kind in hits if kind == "plate")
        skin = sum(1 for _, _, kind in hits if kind == "skin")
        return plate, skin

    def tick(self, level, dt):
        plate, skin = self._counts(self.log.arrows())
        self.lines = [f"arrows landed: {plate + skin}  plate {plate}  skin {skin}"]

    def decide(self, level):
        plate, skin = self._counts(self.log.arrows())
        where = {}
        for kind, region in self.log.regions:
            if kind == "skin":
                where[region] = where.get(region, 0) + 1
        skin_at = ", ".join(f"{r} {n}" for r, n in sorted(where.items())) or "none"
        return "probe", f"{plate + skin} arrows landed: plate {plate}, skin {skin} (skin at: {skin_at})"

    def teardown(self, level):
        self.log.remove()


class PointsVsCapsules(Scene):
    NAME = "points_vs_capsules"
    WATCH = "the same 8 archers: first half his hit body is his mesh (points), second half tubes (capsules)"
    SECONDS, FAST_SECONDS = 16.0, 8.0

    def setup(self, level):
        wear(level, FULL_PLATE)
        ring(level, ARCHER, 8, 185)
        self.log = HitLog(level)
        self.saved = player_module.MESH_HERO_HIT_BODY
        self.counts = {"points": 0, "capsules": 0}
        self.seen = 0
        self.half = (self.FAST_SECONDS if RUNTIME.fast_mode else self.SECONDS) / 2

    def tick(self, level, dt):
        mode = "points" if self.t < self.half else "capsules"
        player_module.MESH_HERO_HIT_BODY = mode
        landed = [ctx for ctx, ok, _ in self.log.arrows() if ok]
        self.counts[mode] += len(landed) - self.seen
        self.seen = len(landed)
        self.lines = [f"hit body now: {mode.upper()}",
                      f"arrows landed: points {self.counts['points']}  capsules {self.counts['capsules']}"]

    def decide(self, level):
        return "probe", f"arrows landed on points {self.counts['points']}, on capsules {self.counts['capsules']}"

    def teardown(self, level):
        player_module.MESH_HERO_HIT_BODY = self.saved
        self.log.remove()


SCENARIOS = (KnockbackMass, ArrowsStop, PlateShove, ArrowsWhereDrawn, PointsVsCapsules)


# --- the driver ----------------------------------------------------------------------------------

class CombatValidationDriver:
    """Level4 calls tick(level, dt) every frame; True when every scene is done."""

    def __init__(self):
        self.queue = [cls for cls in SCENARIOS if RUNTIME.wants_scenario(cls.NAME)]
        self.total = len(self.queue)
        self.scene = None
        self.state = "start"
        self.hold_left = 0.0
        self.started_ms = 0.0
        self.anchor = None
        self.status = ""
        self.details = ""
        contact_debug.ENABLED = True
        contact_debug.KEEP_MS = 4000

    def _overlay(self, phase, extra=()):
        index = self.total - len(self.queue)
        lines = ["COMBAT VALIDATION", f"{index}/{self.total}  {self.scene.NAME}", self.scene.WATCH,
                 f"t = {self.scene.t:4.1f} s"]
        lines += list(self.scene.lines) + list(extra)
        RUNTIME.set_overlay(lines, phase)

    def _reset_hero(self, level):
        hero = level.player
        if self.anchor is None:
            self.anchor = hero.hitbox.center
        hero.hitbox.center = self.anchor
        hero.plant_sprite_on_hitbox()
        hero.velocity.update(0, 0)
        hero.direction.update(0, 0)
        wear(level, ())

    def tick(self, level, dt):
        dt = max(0.0, float(dt or 0.0))
        if dt > 1.0:
            dt /= 1000.0                     # some callers pass milliseconds
        if self.state == "start":
            if not self.queue:
                return True
            self.scene = self.queue.pop(0)()
            remove_enemies(level)
            self._reset_hero(level)
            self.scene.setup(level)
            self.started_ms = time.perf_counter()
            self.state = "run"
        if self.state == "run":
            self.scene.t += dt
            self.scene.tick(level, dt)
            limit = self.scene.FAST_SECONDS if RUNTIME.fast_mode else self.scene.SECONDS
            self._overlay("RUNNING")
            if self.scene.t >= limit:
                self.status, self.details = self.scene.decide(level)
                RUNTIME.record(self.scene.NAME, self.status != "fail", self.details,
                               ms=(time.perf_counter() - self.started_ms) * 1000.0, status=self.status)
                self.hold_left = RUNTIME.hold_seconds
                self.state = "hold"
        if self.state == "hold":
            self._overlay(self.status.upper(), [f"{self.status.upper()}: {self.details}"])
            self.hold_left -= dt
            if self.hold_left <= 0:
                self.scene.teardown(level)
                remove_enemies(level)
                self.state = "start"
        return False
