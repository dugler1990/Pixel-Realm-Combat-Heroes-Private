"""Co-op (Stage C, C2) host side: applying a joiner's relayed hit.

`Level4._apply_relayed_enemy_hit` is what the HOST runs when a joiner's attack
on a shared enemy is forwarded to it. It must find the real enemy by id and put
the relayed damage through the normal `InteractionResolver` so the enemy's
i-frames + retaliation behave exactly as for the host's own hits. Driven against
a real `CombatUnit` + a real resolver via a duck-typed stub (no full Level4).
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

from Settings import monster_data  # noqa: E402
from combat_unit import CombatUnit  # noqa: E402
from Interaction import InteractionResolver  # noqa: E402
from Level4_tmxdev import Level4  # noqa: E402

MONSTER = next(iter(monster_data))


def _real_enemy(level_stub, team_id="enemy"):
    return CombatUnit(
        monster_name=MONSTER, pos=(100, 100), groups=[pygame.sprite.Group()],
        obstacle_sprites=SimpleNamespace(), combat_context={"level": level_stub},
        persistent=False, special_attacks=None, item_drop_info=None, team_id=team_id,
    )


def _host_stub():
    stub = SimpleNamespace(interaction_resolver=InteractionResolver())
    stub.spawner = SimpleNamespace(enemies=[])
    return stub


def test_apply_relayed_hit_reduces_real_enemy_health():
    stub = _host_stub()
    enemy = _real_enemy(stub)
    stub.spawner.enemies = [enemy]
    before = enemy.health
    Level4._apply_relayed_enemy_hit(stub, enemy.id, 30, "weapon")
    assert enemy.health == before - 30   # routed through the resolver -> real damage


def test_apply_relayed_hit_unknown_id_is_noop():
    stub = _host_stub()
    enemy = _real_enemy(stub)
    stub.spawner.enemies = [enemy]
    before = enemy.health
    Level4._apply_relayed_enemy_hit(stub, 999_999, 30, "weapon")  # no such enemy
    assert enemy.health == before


def test_apply_relayed_hit_ignores_missing_fields():
    stub = _host_stub()
    enemy = _real_enemy(stub)
    stub.spawner.enemies = [enemy]
    before = enemy.health
    Level4._apply_relayed_enemy_hit(stub, None, 30, "weapon")
    Level4._apply_relayed_enemy_hit(stub, enemy.id, None, "weapon")
    assert enemy.health == before
