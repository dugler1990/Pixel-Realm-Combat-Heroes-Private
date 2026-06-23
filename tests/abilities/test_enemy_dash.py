"""Headless tests for enemy DashAttack integration."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()

from abilities.protocol import CombatAbilityContext  # noqa: E402
from SpecialAttacks import DashAttack, dash_direction_toward_player  # noqa: E402


class _StubRect:
    def __init__(self, x=0):
        self.x = x
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
    def __init__(self, x=0):
        self.x = x
        self.y = 0

    @property
    def center(self):
        return (self.x, self.y)

    @center.setter
    def center(self, value):
        self.x = value[0]
        self.y = value[1]


class _StubEnemy:
    def __init__(self, x=0, speed=4):
        self.speed = speed
        self.rect = _StubRect(x)
        self.hitbox = _StubHitbox(x)
        self.status = "idle"
        self.frame_index = 0
        self.direction = pygame.math.Vector2(0, 0)
        self.attacking = False
        self._dash_runtime = None
        self.combat_context = {}
        self.frozen = False
        self.speed = speed
        self.move_calls = 0

    def groups(self):
        return []

    def collision(self, QuadTree, entity_quad_tree, speed=0):
        pass

    def move(self, speed=0, QuadTree=None, entity_quad_tree=None):
        self.move_calls += 1

    def is_dash_active(self):
        return getattr(self, "_dash_runtime", None) is not None

    def actions(self, player, quadtree=None):
        if self.is_dash_active():
            return

    def update(self, QuadTree=None, entity_quad_tree=None, dt=None):
        runtime = getattr(self, "_dash_runtime", None)
        if runtime is not None:
            ability = runtime.get("_ability")
            if ability is not None:
                ability.tick(
                    self,
                    CombatAbilityContext.from_enemy(self),
                    dt,
                    QuadTree,
                    entity_quad_tree,
                )
        elif not self.frozen and self.status == "move":
            self.move(speed=self.speed, QuadTree=QuadTree, entity_quad_tree=entity_quad_tree)


class _StubPlayer:
    def __init__(self, x=100):
        self.rect = _StubRect(x)


def test_dash_direction_toward_player():
    enemy = _StubEnemy(x=50)
    player = _StubPlayer(x=100)
    assert dash_direction_toward_player(enemy, player) == "right"

    player.rect.x = 10
    assert dash_direction_toward_player(enemy, player) == "left"


@patch("SpecialAttacks.random.random", return_value=0.0)
def test_dash_attack_execute_starts_runtime(_mock_random):
    attack_config = {
        "cost": 0,
        "speed_mult": 2,
        "duration_ms": 350,
        "collision_mode": "pass_through",
    }
    attack = DashAttack(
        cooldown=1000,
        cooldown_variability=0,
        trigger_conditions=[],
        attack_config=attack_config,
        chance=1.0,
    )
    enemy = _StubEnemy(x=0)
    player = _StubPlayer(x=200)

    attack.execute(enemy, player, {})
    assert enemy._dash_runtime is not None
    assert enemy._dash_runtime["_ability"] is attack.dash_ability
    assert enemy.status == "move"


@patch("SpecialAttacks.random.random", return_value=0.0)
def test_enemy_update_ticks_dash_without_move(_mock_random):
    attack_config = {
        "cost": 0,
        "speed_mult": 2.5,
        "duration_ms": 99999,
        "collision_mode": "pass_through",
    }
    attack = DashAttack(
        cooldown=1000,
        cooldown_variability=0,
        trigger_conditions=[],
        attack_config=attack_config,
        chance=1.0,
    )
    enemy = _StubEnemy(x=0, speed=4)
    player = _StubPlayer(x=200)
    attack.execute(enemy, player, {})

    enemy.update()
    assert enemy.hitbox.x == 10
    assert enemy.move_calls == 0


@patch("SpecialAttacks.random.random", return_value=0.0)
def test_actions_noop_while_dash_active(_mock_random):
    attack = DashAttack(
        cooldown=1000,
        cooldown_variability=0,
        trigger_conditions=[],
        attack_config={"cost": 0, "duration_ms": 99999},
        chance=1.0,
    )
    enemy = _StubEnemy()
    player = _StubPlayer()
    attack.execute(enemy, player, {})
    assert enemy.status == "move"

    enemy.actions(player)
    assert enemy.status == "move"
    assert enemy.is_dash_active()
