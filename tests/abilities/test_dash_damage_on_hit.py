"""Headless tests for DashAbility damage_on_hit collision mode.

The dasher's pixels are tested against bodies found through the real entity tree, which
holds snapshots (HashableRect) whose owner is the body, the way Entity.move puts them
there. Hits apply through the real InteractionResolver.strike.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()

import benchmark_runtime  # noqa: E402,F401  benchmark_broadphase needs it imported first
from benchmark_broadphase import MovingEntityBroadphaseAdapter  # noqa: E402
from abilities.dash import DashAbility  # noqa: E402
from abilities.protocol import CombatAbilityContext  # noqa: E402
from hashRect import HashableRect  # noqa: E402
from Interaction import InteractionContext, InteractionResolver  # noqa: E402


class _Body:
    """A body with no mask, so its whole rect is what can be hit."""

    def __init__(self, body_id, x, y, team_id="player"):
        self.id = body_id
        self.team_id = team_id
        self.rect = pygame.Rect(x, y, 32, 32)
        self.received = []

    def can_receive_interaction(self, ctx):
        return True

    def receive_interaction(self, ctx):
        self.received.append(ctx)


class _Dasher:
    def __init__(self, speed=10):
        self.id = "dasher"
        self.team_id = "enemy"
        self.stats = {"speed": speed}
        self.hitbox = pygame.Rect(0, 0, 32, 32)
        self.rect = self.hitbox.copy()
        self.status = "move"
        self.frame_index = 0
        self.direction = pygame.math.Vector2(0, 0)
        self._dash_runtime = None

    def groups(self):
        return []

    def plant_sprite_on_hitbox(self):
        self.rect.topleft = self.hitbox.topleft


class _RecordingResolver(InteractionResolver):
    """The real resolver and its strike, with apply recorded and the team check fixed."""

    def __init__(self, allowed=True):
        super().__init__()
        self.applied = []
        self.allowed = allowed

    def can_potentially_affect(self, source_team, target_team, kind="damage"):
        return self.allowed

    def apply(self, ctx):
        self.applied.append(ctx)
        return True


class _Level:
    def __init__(self, resolver):
        self.interaction_resolver = resolver


def _tree(*bodies):
    """The real entity tree, holding each body as Entity.move does: a snapshot with owner."""
    tree = MovingEntityBroadphaseAdapter(pygame.Rect(0, 0, 2000, 2000))
    for body in bodies:
        tree.insert(HashableRect(body.rect, body.id, owner=body))
    return tree


def _dash(**config):
    base = {
        "cost": 0,
        "speed_mult": 1,
        "duration_ms": 99999,
        "collision_mode": "damage_on_hit",
        "damage": 12,
        "attack_type": "melee",
    }
    base.update(config)
    return DashAbility("charge", base)


def _start(dash, resolver):
    entity = _Dasher()
    ctx = CombatAbilityContext(combat_context={"level": _Level(resolver)})
    dash.try_start(entity, ctx, direction="right")
    return entity, ctx


def test_damage_on_hit_hits_the_body_not_its_snapshot():
    target = _Body("target-1", 20, 0)
    resolver = _RecordingResolver()
    dash = _dash()
    entity, ctx = _start(dash, resolver)

    dash.tick(entity, ctx, 16, None, _tree(target))

    assert len(resolver.applied) == 1
    applied = resolver.applied[0]
    assert isinstance(applied, InteractionContext)
    assert applied.target is target
    assert applied.amount == 12
    assert applied.source_kind == "dash"


def test_damage_on_hit_misses_a_body_it_does_not_touch():
    target = _Body("target-1", 500, 500)
    resolver = _RecordingResolver()
    dash = _dash()
    entity, ctx = _start(dash, resolver)

    dash.tick(entity, ctx, 16, None, _tree(target))

    assert resolver.applied == []


def test_damage_on_hit_hits_each_body_once_by_default():
    target = _Body("target-1", 20, 0)
    resolver = _RecordingResolver()
    dash = _dash(hit_once_per_target=True)
    entity, ctx = _start(dash, resolver)
    tree = _tree(target)

    dash.tick(entity, ctx, 16, None, tree)
    dash.tick(entity, ctx, 16, None, tree)

    assert len(resolver.applied) == 1
    assert id(target) in entity._dash_runtime["hits"]


def test_damage_on_hit_rehit_ms_zero_hits_every_tick():
    target = _Body("target-1", 20, 0)
    resolver = _RecordingResolver()
    dash = _dash(rehit_ms=0)
    entity, ctx = _start(dash, resolver)
    tree = _tree(target)

    dash.tick(entity, ctx, 16, None, tree)
    dash.tick(entity, ctx, 16, None, tree)

    assert len(resolver.applied) == 2


def test_damage_on_hit_respects_faction_filter():
    target = _Body("target-1", 20, 0)
    resolver = _RecordingResolver(allowed=False)
    dash = _dash()
    entity, ctx = _start(dash, resolver)

    dash.tick(entity, ctx, 16, None, _tree(target))

    assert resolver.applied == []


def test_damage_on_hit_needs_a_resolver():
    target = _Body("target-1", 20, 0)
    dash = _dash()
    entity = _Dasher()
    ctx = CombatAbilityContext(combat_context={})
    dash.try_start(entity, ctx, direction="right")

    dash.tick(entity, ctx, 16, None, _tree(target))

    assert target.received == []
