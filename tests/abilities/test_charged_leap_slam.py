"""Headless tests for ChargedLeapSlamAbility."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()


@pytest.fixture(autouse=True)
def _ensure_display():
    if not pygame.display.get_surface():
        pygame.display.set_mode((64, 64))
    yield


from abilities.leap_slam import ChargedLeapSlamAbility  # noqa: E402
from abilities.protocol import PlayerAbilityContext  # noqa: E402
from hashRect import HashableRect  # noqa: E402
from Interaction import InteractionContext, InteractionResolver  # noqa: E402
from Settings import ability_data  # noqa: E402


class _StubRect:
    def __init__(self, x=0, y=0):
        self.x = x
        self.y = y
        self.width = 32
        self.height = 32

    @property
    def center(self):
        return (self.x, self.y)

    @center.setter
    def center(self, value):
        self.x = value[0]
        self.y = value[1]


class _StubHitbox:
    def __init__(self, x=0, y=0):
        self.x = x
        self.y = y

    @property
    def center(self):
        return (self.x, self.y)

    @center.setter
    def center(self, value):
        self.x = value[0]
        self.y = value[1]


class _StubTarget:
    def __init__(self, x=0, y=0, team_id="enemy", target_id="target-1"):
        self.id = target_id
        self.team_id = team_id
        self.rect = _StubRect(x, y)
        self.hitbox = _StubHitbox(x, y)
        self.velocity = pygame.math.Vector2(0, 0)
        self._dash_runtime = None
        self._leap_runtime = None
        self.damage_received = 0.0

    def cancel_displacement_abilities(self):
        from Entity import Entity

        Entity.cancel_displacement_abilities(self)

    def apply_impulse(self, force, follow_through=0.5):
        from Entity import Entity

        Entity.apply_impulse(self, force, follow_through=follow_through)

    def can_receive_interaction(self, ctx):
        from Entity import Entity

        return Entity.can_receive_interaction(self, ctx)

    def receive_interaction(self, ctx):
        from Entity import Entity

        if ctx.kind == "damage":
            self.damage_received += ctx.amount or 0
        Entity.receive_interaction(self, ctx)


class _StubEntity:
    def __init__(self, energy=30, x=100, y=100):
        self.energy = energy
        self.team_id = "player"
        self.id = "player-1"
        self.rect = _StubRect(x, y)
        self.hitbox = _StubHitbox(x, y)
        self.status = "right_idle"
        self.frame_index = 0
        self.direction = pygame.math.Vector2(1, 0)
        self.attacking = False
        self._charge_runtime = None
        self._leap_runtime = None
        self._dash_runtime = None
        self.impulse_follow_through = 0.5
        self.collision_calls = 0
        self.level = SimpleNamespace(interaction_resolver=InteractionResolver())

    def groups(self):
        return []

    def collision(self, QuadTree, entity_quad_tree, speed=0):
        self.collision_calls += 1

    def get_direction_as_string(self):
        return "right"


class _FakeQuadTree:
    def __init__(self, targets):
        self._targets = list(targets)

    def hit(self, query):
        return list(self._targets)


def _ability():
    return ChargedLeapSlamAbility("leap_slam", dict(ability_data["leap_slam"]))


def _ctx():
    return PlayerAbilityContext(
        animation_player=None,
        create_trap=lambda *a, **k: None,
    )


def test_energy_not_spent_on_press_only():
    ability = _ability()
    entity = _StubEntity(energy=20)
    cost = ability.config["cost"]
    assert ability.on_press(entity, _ctx(), direction="right") is True
    assert entity._charge_runtime is not None
    assert entity.energy == 20
    entity._charge_runtime = None


def test_energy_spent_once_on_release_launch():
    ability = _ability()
    entity = _StubEntity(energy=20)
    cost = ability.config["cost"]
    ability.on_press(entity, _ctx(), direction="right")
    assert ability.on_release(entity, _ctx(), direction="right") is True
    assert entity._leap_runtime is not None
    assert entity.energy == 20 - cost
    assert entity._charge_runtime is None


def test_on_release_prefers_charge_direction():
    ability = _ability()
    entity = _StubEntity()
    ability.on_press(entity, _ctx(), direction="left")
    assert ability.on_release(entity, _ctx(), direction="right") is True
    assert entity._leap_runtime["direction"] == "left"
    assert entity._leap_runtime["end_x"] < entity._leap_runtime["start_x"]


def test_launch_up_moves_vertically():
    ability = _ability()
    entity = _StubEntity()
    entity.hitbox.y = 200
    ability._launch(entity, _ctx(), "up", 1.0)
    max_range = ability.config.get("max_vertical_range", ability.config["max_horizontal_range"])
    assert entity._leap_runtime["end_y"] == entity._leap_runtime["start_y"] - int(max_range)
    assert entity._leap_runtime["end_x"] == entity._leap_runtime["start_x"]


def test_launch_horizontal_range_scales_with_charge_ratio():
    ability = _ability()
    entity = _StubEntity()
    ability._launch(entity, _ctx(), "right", 0.5)
    max_range = ability.config["max_horizontal_range"]
    assert entity._leap_runtime["end_x"] == entity._leap_runtime["start_x"] + int(max_range * 0.5)


def test_air_duration_scales_with_charge():
    ability = _ability()
    min_ms = ability.config["air_duration_min_ms"]
    max_ms = ability.config["air_duration_max_ms"]
    low = ability._air_duration_ms(0.0)
    high = ability._air_duration_ms(1.0)
    mid = ability._air_duration_ms(0.5)
    assert low == min_ms
    assert high == max_ms
    assert low < mid < high


def test_launch_snap_moves_immediately():
    ability = _ability()
    entity = _StubEntity(x=100, y=100)
    start_x = entity.hitbox.x
    ability._launch(entity, _ctx(), "right", 1.0)
    assert entity.hitbox.x == start_x + ability.config.get("launch_snap_px", 0)


def test_travel_progress_ease_out():
    ability = _ability()
    assert ability._travel_progress(0.0) == 0.0
    assert ability._travel_progress(1.0) == 1.0
    assert ability._travel_progress(0.5) > 0.5


def test_arc_offset_peaks_mid_flight():
    ability = _ability()
    rise = ability.config["arc_rise_ratio"]
    hang = ability.config["arc_hang_ratio"]
    rise_peak = ability._arc_offset(rise, 100.0)
    hang_peak = ability._arc_offset(min(0.95, rise + hang * 0.5), 100.0)
    end = ability._arc_offset(1.0, 100.0)
    assert rise_peak > 0
    assert hang_peak == pytest.approx(100.0)
    assert end == pytest.approx(0.0)


def test_airborne_tick_does_not_call_collision():
    ability = _ability()
    entity = _StubEntity()
    ability._launch(entity, _ctx(), "right", 1.0)
    runtime = entity._leap_runtime
    runtime["start_time"] = pygame.time.get_ticks()
    runtime["end_time"] = runtime["start_time"] + 400
    ability._tick_airborne(entity, runtime, dt=1 / 60)
    assert entity.collision_calls == 0
    assert runtime["phase"] == "airborne"


def test_air_control_accumulates_with_direction():
    ability = _ability()
    entity = _StubEntity()
    entity.direction = pygame.math.Vector2(1, 0)
    ability._launch(entity, _ctx(), "right", 1.0)
    runtime = entity._leap_runtime
    ability._accumulate_air_control(entity, runtime, 1 / 60)
    assert runtime["air_steer_x"] > 0
    assert runtime["air_steer_y"] == 0.0


def test_landing_aoe_damage_and_impulse_falloff():
    ability = _ability()
    entity = _StubEntity(x=0, y=0)
    center_target = _StubTarget(x=0, y=0, team_id="enemy")
    edge_target = _StubTarget(x=100, y=0, team_id="enemy", target_id="target-2")
    quadtree = _FakeQuadTree([center_target, edge_target])
    runtime = {
        "charge_ratio": 1.0,
        "impact_center": (0, 0),
        "direction": "right",
        "_ability": ability,
    }
    ability._resolve_landing_aoe(entity, _ctx(), quadtree, runtime)
    assert center_target.damage_received == pytest.approx(25.0)
    assert center_target.hitbox.x == pytest.approx(14.0)
    edge_knockback = 14.0 * (1.0 - 100.0 / 120.0)
    assert edge_target.damage_received == pytest.approx(25.0 * (1.0 - 100.0 / 120.0))
    assert edge_target.hitbox.x == pytest.approx(100.0 + int(edge_knockback))


def test_arc_height_scales_with_charge_ratio():
    ability = _ability()
    min_h = ability.config["min_arc_height"]
    max_h = ability.config["max_arc_height"]
    assert ability._arc_height_for_ratio(0.0) == pytest.approx(min_h)
    assert ability._arc_height_for_ratio(1.0) == pytest.approx(max_h)
    assert ability._arc_height_for_ratio(0.5) == pytest.approx(min_h + (max_h - min_h) * 0.5)


def test_charge_ratio_tracks_hold_time_smoothly():
    ability = _ability()
    entity = _StubEntity()
    start = pygame.time.get_ticks()
    entity._charge_runtime = {
        "start_time": start,
        "direction": "right",
        "charge_ratio": 0.0,
        "_ability": ability,
    }
    assert ability.charge_ratio(entity) == pytest.approx(0.0)
    entity._charge_runtime["start_time"] = start - 500
    max_hold = ability.config["max_hold_ms"]
    assert ability.charge_ratio(entity) == pytest.approx(500 / max_hold)


def test_min_charge_ratio_on_quick_release():
    ability = _ability()
    entity = _StubEntity()
    entity._charge_runtime = {
        "start_time": pygame.time.get_ticks(),
        "direction": "right",
        "charge_ratio": 0.0,
        "_ability": ability,
    }
    ratio = ability._compute_charge_ratio(entity._charge_runtime)
    assert ratio == pytest.approx(ability.config["min_charge_ratio"])
