"""Co-op (Stage C, CS3) server side: applying a client's relayed hit.

`ServerLevel.apply_enemy_hit` is what the SERVER runs when a client's attack on a
shared enemy is relayed to it (server-authoritative pivot -- replaces the old
host-applied path). It must find the authoritative enemy by id and put the
relayed damage through the real `InteractionResolver` so the enemy's i-frames +
retaliation behave exactly as in singleplayer. Driven against a real ServerLevel
(real Spawner + CombatUnit + resolver) headless.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT / "Code", REPO_ROOT / "Server"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pygame  # noqa: E402
import pytest  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

from server_level import ServerLevel  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_software_display():
    # See test_server_enemy_sim: reset a (possibly OpenGL-polluted) display so the
    # real CombatUnit surface loads don't segfault in the shared suite.
    pygame.display.quit()
    pygame.display.init()
    pygame.display.set_mode((64, 64))
    yield


def _level_with_squid():
    level = ServerLevel(world_w=20000, world_h=20000)
    enemy = level.spawn_enemy({"type": "squid", "pos": (10, 10)})
    return level, enemy


def test_apply_relayed_hit_reduces_real_enemy_health():
    level, enemy = _level_with_squid()
    before = enemy.health
    assert level.apply_enemy_hit(enemy.id, 30, "weapon") is True
    assert enemy.health == before - 30   # routed through the resolver -> real damage


def test_apply_relayed_hit_unknown_id_is_noop():
    level, enemy = _level_with_squid()
    before = enemy.health
    assert level.apply_enemy_hit(999_999, 30, "weapon") is False
    assert enemy.health == before


def test_apply_relayed_hit_ignores_missing_fields():
    level, enemy = _level_with_squid()
    before = enemy.health
    assert level.apply_enemy_hit(None, 30, "weapon") is False
    assert level.apply_enemy_hit(enemy.id, None, "weapon") is False
    assert enemy.health == before
