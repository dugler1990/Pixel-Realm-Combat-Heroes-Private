"""Tests for InteractionContext impulse knockback."""

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

from Interaction import InteractionContext, InteractionResolver  # noqa: E402
from combat_unit import CombatUnit  # noqa: E402
from Player import BasePlayer  # noqa: E402
from Settings import monster_data  # noqa: E402


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
        self.y = 0 if False else y

    @property
    def center(self):
        return (self.x, self.y)

    @center.setter
    def center(self, value):
        self.x = value[0]
        self.y = value[1]


class _StubEntity:
    def __init__(self, team_id="enemy"):
        self.team_id = team_id
        self.rect = _StubRect()
        self.hitbox = _StubHitbox()
        self.velocity = pygame.math.Vector2(0, 0)
        self._dash_runtime = None
        self._leap_runtime = None
        self.status = "idle"

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

        Entity.receive_interaction(self, ctx)


class _StubPlayer:
    team_id = "player"

    def __init__(self):
        self.rect = _StubRect()
        self.hitbox = _StubHitbox()
        self.velocity = pygame.math.Vector2(0, 0)
        self._dash_runtime = None
        self._leap_runtime = None

    def cancel_displacement_abilities(self):
        from Entity import Entity

        Entity.cancel_displacement_abilities(self)

    def apply_impulse(self, force, follow_through=0.5):
        from Entity import Entity

        Entity.apply_impulse(self, force, follow_through=follow_through)

    def can_receive_interaction(self, ctx):
        return BasePlayer.can_receive_interaction(self, ctx)

    def receive_interaction(self, ctx):
        if ctx.kind == "impulse":
            force = pygame.math.Vector2(ctx.impulse_x or 0, ctx.impulse_y or 0)
            self.apply_impulse(force)
            return
        if ctx.kind == "damage":
            self.damage_received = ctx.amount


MONSTER = next(iter(monster_data))


def _resolver():
    return InteractionResolver()


def test_hostile_impulse_displaces_stub_entity():
    target = _StubEntity(team_id="enemy")
    ctx = InteractionContext(
        kind="impulse",
        source_kind="leap_slam",
        source_team="player",
        target=target,
        impulse_x=10,
        impulse_y=-4,
    )
    assert _resolver().apply(ctx) is True
    assert target.hitbox.x == 10
    assert target.hitbox.y == -4


def test_player_rejects_ally_impulse():
    player = _StubPlayer()
    ctx = InteractionContext(
        kind="impulse",
        source_kind="test",
        source_team="player",
        target=player,
        impulse_x=20,
        impulse_y=0,
    )
    assert player.can_receive_interaction(ctx) is False
    assert _resolver().apply(ctx) is False
    assert player.hitbox.x == 0


def test_player_accepts_hostile_impulse():
    player = _StubPlayer()
    ctx = InteractionContext(
        kind="impulse",
        source_kind="test",
        source_team="enemy",
        target=player,
        impulse_x=15,
        impulse_y=0,
    )
    assert player.can_receive_interaction(ctx) is True
    assert _resolver().apply(ctx) is True
    assert player.hitbox.x == 15


def test_combat_unit_rejects_ally_impulse():
    level_stub = SimpleNamespace(interaction_resolver=_resolver())
    enemy = CombatUnit(
        monster_name=MONSTER,
        pos=(100, 100),
        groups=[pygame.sprite.Group()],
        obstacle_sprites=SimpleNamespace(),
        combat_context={"level": level_stub},
        persistent=False,
        special_attacks=None,
        item_drop_info=None,
        team_id="enemy",
    )
    ctx = InteractionContext(
        kind="impulse",
        source_kind="test",
        source_team="enemy",
        target=enemy,
        impulse_x=12,
        impulse_y=0,
    )
    assert enemy.can_receive_interaction(ctx) is False
    assert _resolver().apply(ctx) is False


def test_combat_unit_accepts_hostile_impulse():
    level_stub = SimpleNamespace(interaction_resolver=_resolver())
    enemy = CombatUnit(
        monster_name=MONSTER,
        pos=(100, 100),
        groups=[pygame.sprite.Group()],
        obstacle_sprites=SimpleNamespace(),
        combat_context={"level": level_stub},
        persistent=False,
        special_attacks=None,
        item_drop_info=None,
        team_id="enemy",
    )
    before_x = enemy.hitbox.x
    ctx = InteractionContext(
        kind="impulse",
        source_kind="test",
        source_team="player",
        target=enemy,
        impulse_x=8,
        impulse_y=3,
    )
    assert enemy.can_receive_interaction(ctx) is True
    assert _resolver().apply(ctx) is True
    assert enemy.hitbox.x == before_x + 8


def test_impulse_cancels_dash_runtime():
    target = _StubEntity()
    target._dash_runtime = {"direction": "right", "_ability": None}

    class _EndAbility:
        def _end(self, entity, runtime):
            entity._dash_runtime = None
            entity.status = "idle"

    target._dash_runtime["_ability"] = _EndAbility()
    ctx = InteractionContext(
        kind="impulse",
        source_kind="test",
        source_team="player",
        target=target,
        impulse_x=5,
        impulse_y=0,
    )
    _resolver().apply(ctx)
    assert target._dash_runtime is None
    assert target.hitbox.x == 5


def test_impulse_cancels_leap_runtime():
    target = _StubEntity()
    target._leap_runtime = {"phase": "airborne", "_ability": None}

    class _EndAbility:
        def _end(self, entity, runtime):
            entity._leap_runtime = None

    target._leap_runtime["_ability"] = _EndAbility()
    ctx = InteractionContext(
        kind="impulse",
        source_kind="test",
        source_team="player",
        target=target,
        impulse_x=7,
        impulse_y=0,
    )
    _resolver().apply(ctx)
    assert target._leap_runtime is None
    assert target.hitbox.x == 7
