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
import temperature
import Player as player_module
from abilities.leap_slam import ChargedLeapSlamAbility
from combat_validation_runtime import COMBAT_VALIDATION_RUNTIME as RUNTIME
from conditions import condition, speed_of
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
        self.wounds = []          # (kind, health delta, flinched: the hit stamped hit_time)
        self.stopped = []
        self._original = level.interaction_resolver.land
        self._effect = ParticleEffect
        self._stop = ParticleEffect.stop
        hero = level.player
        log = self

        def land(ctx):
            health, hit_time = hero.health, hero.hit_time
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
                log.wounds.append((kind, hero.health - health, hero.hit_time != hit_time))
            return landed

        def stop(sprite):
            if getattr(sprite, "attack_def", None) is attack("arrow"):
                log.stopped.append(sprite)
            return log._stop(sprite)

        # land, not apply: strike calls land itself, and apply goes through land.
        level.interaction_resolver.land = land
        ParticleEffect.stop = stop

    def remove(self):
        del self.level.interaction_resolver.land
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


class PlateStops(Scene):
    NAME = "plate_stops"
    WATCH = "plated barb: grey dots take no health and no flinch; red dots on the bare head do"
    SECONDS, FAST_SECONDS = 14.0, 8.0

    def setup(self, level):
        wear(level, FULL_PLATE)
        ring(level, ARCHER, 8, 185)
        self.log = HitLog(level)
        hero = level.player
        hero.health = hero.max_stats["health"]

    def tick(self, level, dt):
        plate = skin = hurt = 0
        for kind, delta, _flinched in self.log.wounds:
            if kind == "plate":
                plate += 1
            elif kind == "skin":
                skin += 1
                if delta < 0:
                    hurt += 1
        self.lines = [f"plate {plate} (no wound)   skin {skin} (hurt {hurt})   health {level.player.health:g}"]

    def decide(self, level):
        plate_bad = 0
        plate = skin = hurt = 0
        for kind, delta, flinched in self.log.wounds:
            if kind == "plate":
                plate += 1
                if delta != 0 or flinched:
                    plate_bad += 1
            elif kind == "skin":
                skin += 1
                if delta < 0:
                    hurt += 1
        details = f"plate {plate} (bad {plate_bad}), skin {skin} (hurt {hurt}), health {level.player.health:g}"
        ok = plate > 0 and hurt > 0 and plate_bad == 0
        return ("pass" if ok else "fail"), details

    def teardown(self, level):
        self.log.remove()


class Haste(Scene):
    """The one thing that grants haste. Hold a direction: faster until 8 s, then today's speed."""

    NAME = "haste"
    WATCH = "Hold a direction. He is faster until the line says the buff ended, then he is back to normal."
    SECONDS = 10.0
    FAST_SECONDS = 9.0

    def setup(self, level):
        hero = level.player
        self.base = hero.stats["speed"]
        self.saw_fast = False
        level.condition_clock.start(hero, "haste", pygame.time.get_ticks())

    def tick(self, level, dt):
        hero = level.player
        now = pygame.time.get_ticks()
        speed = speed_of(hero)
        if speed == self.base + 4:
            self.saw_fast = True
        inst = next(iter(hero.conditions.values()), None)
        if inst is None:
            left = "buff ended"
        else:
            left = f"haste {max(0.0, (inst.end_ms - now) / 1000.0):.1f}s left"
        self.lines = [f"speed {speed:g}   base {self.base:g}", left]

    def decide(self, level):
        hero = level.player
        speed = speed_of(hero)
        gone = condition("haste").id not in hero.conditions
        ok = self.saw_fast and gone and speed == self.base
        return ("pass" if ok else "fail"), (
            f"speed {speed:g} base {self.base:g} saw_fast {self.saw_fast} ended {gone}"
        )


def _warm_lines(hero):
    now = pygame.time.get_ticks()
    return [f"health {hero.health:.0f}",
            f"skin {temperature.skin(hero, now):+.1f}  outer {temperature.outer(hero, now):+.1f}",
            f"red {getattr(hero, 'heat_shade', None) or '-'}  blue {getattr(hero, 'cold_shade', None) or '-'}"
            f"  speed {speed_of(hero):g}"]


class _Warm(Scene):
    """Temperature scenes: the level's air and sun, plate or naked, no health recovery. Probes:
    the lines are for watching (docs/damage/PLAN_temperature.md, feel targets)."""

    AIR = 0.0
    SUN = 0.0
    PLATE = True

    def setup(self, level):
        hero = level.player
        wear(level, FULL_PLATE if self.PLATE else ())
        now = pygame.time.get_ticks()
        temperature.set_air(level, self.AIR, now, [hero])
        temperature.set_sun(level, self.SUN, now, [hero])
        self.recovery = hero.health_recovery
        hero.health_recovery = lambda: None
        self.start = self.low = hero.health
        self.red = self.blue = None

    def tick(self, level, dt):
        hero = level.player
        self.low = min(self.low, hero.health)
        self.red = getattr(hero, "heat_shade", None) or self.red
        self.blue = getattr(hero, "cold_shade", None) or self.blue
        self.lines = [f"lost {self.start - self.low:.0f}"] + _warm_lines(hero)

    def decide(self, level):
        now = pygame.time.get_ticks()
        hero = level.player
        return "probe", (f"lost {self.start - self.low:.0f} red {self.red or '-'} blue {self.blue or '-'} "
                         f"skin {temperature.skin(hero, now):+.1f} outer {temperature.outer(hero, now):+.1f}")

    def teardown(self, level):
        level.player.health_recovery = self.recovery


class Fire(_Warm):
    NAME = "fire"
    WATCH = "Full plate. A demon dog spits fire: the plate goes red, the skin warms slowly, the red fades."
    SECONDS = 12.0
    FAST_SECONDS = 10.0

    def setup(self, level):
        super().setup(level)
        spawn_at(level, "demon_dog", -220, 40)


class Ice(_Warm):
    NAME = "ice"
    WATCH = "Naked. The ghost holds you (no hits): mild blue, no health lost."
    PLATE = False
    SECONDS = 20.0
    FAST_SECONDS = 14.0

    def setup(self, level):
        super().setup(level)
        self.ghost = spawn_at(level, "ice_ghost", 120, 0)


class IceNaked(_Warm):
    NAME = "ice_naked"
    WATCH = "Naked, ice (air -30). Blue, then health falls from about 47 s (vitality 20)."
    AIR, SUN, PLATE = -30.0, 0.3, False
    SECONDS = 80.0
    FAST_SECONDS = 4.0


class Desert(_Warm):
    NAME = "desert"
    WATCH = "Full plate, desert, a slide every second: red, health falls from about 12 s."
    AIR, SUN = 10.0, 1.0
    SECONDS = 40.0
    FAST_SECONDS = 4.0

    def setup(self, level):
        super().setup(level)
        self.slides = 0

    def tick(self, level, dt):
        if self.t >= self.slides + 1:
            temperature.exert(level.player, 20, pygame.time.get_ticks())
            self.slides += 1
        super().tick(level, dt)
        self.lines.insert(0, f"slides {self.slides}")


def _heat_patch(level, dx, dy, w, h):
    """One heat area (the maps' own heat), drawn with the red debug outline."""
    from EffectArea import EffectArea
    from effect_cell_grid import EffectCellGrid
    from QuadTree import QuadTree, QuadTreeManager

    feet = level.player.hitbox.midbottom
    rect = pygame.Rect(int(feet[0] + dx), int(feet[1] + dy - h), w, h)
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    surf.fill((255, 255, 255, 255))
    area = EffectArea(rect, pygame.mask.from_surface(surf), {"heat": 100.0}, _id="validation_heat")
    layout = level.layout_manager
    if layout.effect_quad_trees is None:
        layout.effect_quad_trees = {}
    layout.effect_quad_trees["validation_heat"] = QuadTree(
        [area], depth=4, bounding_rect=rect.inflate(800, 800), manager=QuadTreeManager())
    layout.all_effect_areas = list(getattr(layout, "all_effect_areas", None) or []) + [area]
    layout.effect_cell_grid = EffectCellGrid.build(
        layout.all_effect_areas, layout.TILESIZE, layout.csv_layout_width, layout.csv_layout_height)
    layout.visible_sprites.floor_patches.append((rect, (230, 70, 10)))     # lava, on the floor
    return rect


class Lava(_Warm):
    NAME = "lava"
    WATCH = "Full plate. You start in the lava (orange). Walk out: the plate heats, then cools."
    SECONDS = 20.0
    FAST_SECONDS = 4.0

    def setup(self, level):
        super().setup(level)
        hero = level.player
        self.box = _heat_patch(level, 80, 20, 160, 120)
        self.home = hero.hitbox.midbottom
        hero.hitbox.midbottom = self.box.center     # start in it; then he is free to walk
        hero.plant_sprite_on_hitbox()

    def tick(self, level, dt):
        if RUNTIME.fast_mode and self.t >= 1.6:     # headless only: walk him out
            hero = level.player
            hero.hitbox.midbottom = self.home
            hero.plant_sprite_on_hitbox()
            hero.velocity.update(0, 0)
        super().tick(level, dt)

    def teardown(self, level):
        super().teardown(level)
        from effect_cell_grid import EffectCellGrid
        layout = level.layout_manager
        if layout.effect_quad_trees:
            layout.effect_quad_trees.pop("validation_heat", None)
        layout.all_effect_areas = [a for a in layout.all_effect_areas if getattr(a, "_id", None) != "validation_heat"]
        layout.effect_cell_grid = EffectCellGrid.build(
            layout.all_effect_areas, layout.TILESIZE, layout.csv_layout_width, layout.csv_layout_height)
        layout.visible_sprites.floor_patches.clear()


SCENARIOS = (KnockbackMass, ArrowsStop, PlateShove, ArrowsWhereDrawn, PointsVsCapsules, PlateStops,
             Haste, Fire, Ice, IceNaked, Desert, Lava)


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
        now = pygame.time.get_ticks()           # a fresh temperature at mild air, no sun
        level.air = level.sun = 0.0
        temperature.forget(hero, now)
        temperature.join(hero, level, now)
        hero.heat_shade = hero.cold_shade = hero.heat_piece = None
        hero.heat_on_skin = False
        clock = getattr(level, "condition_clock", None)
        if clock is not None:
            for name in ("chilled", "hot_shell", "burning"):
                clock.cure(hero, name)

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
