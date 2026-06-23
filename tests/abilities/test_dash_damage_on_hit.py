"""Headless tests for DashAbility damage_on_hit collision mode."""

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

from abilities.dash import DashAbility  # noqa: E402
from abilities.protocol import CombatAbilityContext  # noqa: E402
from Interaction import InteractionContext  # noqa: E402


class _StubRect:
    def __init__(self):
        self._rect = pygame.Rect(0, 0, 32, 32)

    @property
    def center(self):
        return self._rect.center

    @center.setter
    def center(self, value):
        self._rect.center = value

    @property
    def left(self):
        return self._rect.left

    @property
    def right(self):
        return self._rect.right

    @property
    def top(self):
        return self._rect.top

    @property
    def bottom(self):
        return self._rect.bottom

    @property
    def width(self):
        return self._rect.width

    @property
    def height(self):
        return self._rect.height


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


class _StubTarget:
    def __init__(self, target_id="target-1", team_id="player"):
        self.id = target_id
        self.team_id = team_id
        self.rect = _StubRect()
        self.received = []

    def can_receive_interaction(self, ctx):
        return True

    def receive_interaction(self, ctx):
        self.received.append(ctx)


class _StubEntity:
    def __init__(self, speed=10):
        self.id = "dasher"
        self.team_id = "enemy"
        self.stats = {"speed": speed}
        self.rect = _StubRect()
        self.hitbox = _StubHitbox()
        self.status = "move"
        self.frame_index = 0
        self.direction = pygame.math.Vector2(0, 0)
        self._dash_runtime = None

    def groups(self):
        return []


class _StubQuadTree:
    def __init__(self, hits):
        self._hits = hits

    def hit(self, query):
        return self._hits


class _RecordingResolver:
    def __init__(self, allowed=True):
        self.applied = []
        self.allowed = allowed

    def can_potentially_affect(self, source_team, target_team, ctx):
        return self.allowed

    def apply(self, ctx):
        self.applied.append(ctx)
        return True


class _StubLevel:
    def __init__(self, resolver):
        self.interaction_resolver = resolver


def test_damage_on_hit_applies_via_resolver():
    target = _StubTarget()
    entity = _StubEntity()
    resolver = _RecordingResolver()
    level = _StubLevel(resolver)
    ctx = CombatAbilityContext(combat_context={"level": level})
    quadtree = _StubQuadTree([target])

    dash = DashAbility(
        "charge",
        {
            "cost": 0,
            "speed_mult": 1,
            "duration_ms": 300,
            "collision_mode": "damage_on_hit",
            "damage": 12,
            "attack_type": "melee",
        },
    )
    dash.try_start(entity, ctx, direction="right")
    dash.tick(entity, ctx, 16, None, quadtree)

    assert len(resolver.applied) == 1
    applied = resolver.applied[0]
    assert isinstance(applied, InteractionContext)
    assert applied.amount == 12
    assert applied.target is target
    assert applied.source_kind == "dash"


def test_damage_on_hit_hit_once_per_target():
    target = _StubTarget()
    entity = _StubEntity()
    resolver = _RecordingResolver()
    level = _StubLevel(resolver)
    ctx = CombatAbilityContext(combat_context={"level": level})
    quadtree = _StubQuadTree([target])

    dash = DashAbility(
        "charge",
        {
            "cost": 0,
            "speed_mult": 1,
            "duration_ms": 99999,
            "collision_mode": "damage_on_hit",
            "damage": 5,
            "hit_once_per_target": True,
        },
    )
    dash.try_start(entity, ctx, direction="right")
    entity._dash_runtime["end_time"] = 999999

    dash.tick(entity, ctx, 16, None, quadtree)
    dash.tick(entity, ctx, 16, None, quadtree)

    assert len(resolver.applied) == 1


def test_damage_on_hit_respects_faction_filter():
    target = _StubTarget()
    entity = _StubEntity()
    resolver = _RecordingResolver(allowed=False)
    level = _StubLevel(resolver)
    ctx = CombatAbilityContext(combat_context={"level": level})
    quadtree = _StubQuadTree([target])

    dash = DashAbility(
        "charge",
        {
            "cost": 0,
            "collision_mode": "damage_on_hit",
            "damage": 5,
            "duration_ms": 300,
        },
    )
    dash.try_start(entity, ctx, direction="right")
    dash.tick(entity, ctx, 16, None, quadtree)

    assert len(resolver.applied) == 0


def test_damage_on_hit_fallback_receive_interaction():
    target = _StubTarget()
    entity = _StubEntity()
    ctx = CombatAbilityContext(combat_context={})
    quadtree = _StubQuadTree([target])

    dash = DashAbility(
        "charge",
        {
            "cost": 0,
            "collision_mode": "damage_on_hit",
            "damage": 7,
            "duration_ms": 300,
        },
    )
    dash.try_start(entity, ctx, direction="right")
    dash.tick(entity, ctx, 16, None, quadtree)

    assert len(target.received) == 1
    assert target.received[0].amount == 7
