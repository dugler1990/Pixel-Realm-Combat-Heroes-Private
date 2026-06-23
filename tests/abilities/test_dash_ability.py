"""Headless tests for DashAbility."""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()

from abilities.dash import DashAbility, entity_speed, validate_collision_mode  # noqa: E402
from abilities.protocol import PlayerAbilityContext  # noqa: E402
from Settings import evasion_data  # noqa: E402


class _StubRect:
    def __init__(self):
        self.x = 0
        self.y = 0
        self.width = 32
        self.height = 32

    @property
    def center(self):
        return (self.x, self.y)

    @center.setter
    def center(self, value):
        self.x = value[0]
        self.y = value[1]

    @property
    def centerx(self):
        return self.x


class _StubHitbox:
    def __init__(self):
        self.x = 0
        self.y = 0

    @property
    def center(self):
        return (self.x, self.y)

    @center.setter
    def center(self, value):
        self.x = value[0]
        self.y = value[1]


class _StubEntity:
    def __init__(self, speed=10, energy=30, collision_blocks=False):
        self.stats = {"speed": speed}
        self.energy = energy
        self.rect = _StubRect()
        self.hitbox = _StubHitbox()
        self.status = "right_idle"
        self.frame_index = 0
        self.direction = pygame.math.Vector2(0, 0)
        self.attacking = False
        self._dash_runtime = None
        self.collision_calls = 0
        self.collision_blocks = collision_blocks

    def groups(self):
        return []

    def collision(self, QuadTree, entity_quad_tree, speed=0):
        self.collision_calls += 1
        if self.collision_blocks:
            self.hitbox.x -= int(speed) if speed > 0 else 0


@pytest.fixture
def dash():
    return DashAbility("slide", evasion_data["slide"])


def test_try_start_spends_energy_once(dash):
    entity = _StubEntity(energy=30)
    ctx = PlayerAbilityContext()
    cost = evasion_data["slide"]["cost"]

    assert dash.try_start(entity, ctx, direction="right") is True
    assert entity.energy == 30 - cost
    assert entity._dash_runtime is not None
    assert entity._dash_runtime["_ability"] is dash

    assert dash.try_start(entity, ctx, direction="right") is False
    assert entity.energy == 30 - cost


def test_pass_through_does_not_call_collision(dash):
    entity = _StubEntity()
    ctx = PlayerAbilityContext()
    dash.try_start(entity, ctx, direction="right")

    dash.tick(entity, ctx, 16, None, None)
    assert entity.collision_calls == 0
    assert entity.hitbox.x == 30


def test_resolve_calls_collision():
    config = {
        **evasion_data["slide"],
        "collision_mode": "resolve",
    }
    dash = DashAbility("slide", config)
    entity = _StubEntity()
    ctx = PlayerAbilityContext()
    dash.try_start(entity, ctx, direction="right")

    dash.tick(entity, ctx, 16, None, None)
    assert entity.collision_calls == 1
    assert entity.hitbox.x == 30


def test_resolve_stop_on_wall_ends_early():
    config = {
        **evasion_data["slide"],
        "collision_mode": "resolve",
        "stop_on_wall": True,
    }
    dash = DashAbility("slide", config)
    entity = _StubEntity(collision_blocks=True)
    ctx = PlayerAbilityContext()
    dash.try_start(entity, ctx, direction="right")
    entity._dash_runtime["end_time"] = 99999

    dash.tick(entity, ctx, 16, None, None)
    assert entity._dash_runtime is None
    assert entity.status == "right_idle"


def test_tick_accumulates_dx_until_end(dash, monkeypatch):
    entity = _StubEntity(speed=10)
    ctx = PlayerAbilityContext()

    tick_values = [100, 116, 132, 400]
    monkeypatch.setattr("abilities.dash.pygame.time.get_ticks", lambda: tick_values.pop(0))

    dash.try_start(entity, ctx, direction="right")
    entity._dash_runtime["end_time"] = 300

    dash.tick(entity, ctx, 16, None, None)
    assert entity.hitbox.x == 30
    dash.tick(entity, ctx, 16, None, None)
    assert entity.hitbox.x == 60
    dash.tick(entity, ctx, 16, None, None)
    assert entity._dash_runtime is None
    assert entity.status == "right_idle"


def test_entity_speed_from_stats():
    entity = _StubEntity(speed=10)
    assert entity_speed(entity) == 10


def test_entity_speed_from_combat_unit_style():
    entity = _StubEntity()
    del entity.stats
    entity.speed = 4
    assert entity_speed(entity) == 4


def test_validate_collision_modes():
    validate_collision_mode("pass_through")
    validate_collision_mode("resolve")
    validate_collision_mode("damage_on_hit")
    with pytest.raises(ValueError):
        validate_collision_mode("unknown_mode")


def test_player_slide_config_still_pass_through():
    dash = DashAbility("slide", evasion_data["slide"])
    assert dash.collision_mode == "pass_through"


def test_is_active_reflects_runtime(dash):
    entity = _StubEntity()
    assert dash.is_active(entity) is False
    dash.try_start(entity, PlayerAbilityContext(), direction="left")
    assert dash.is_active(entity) is True
