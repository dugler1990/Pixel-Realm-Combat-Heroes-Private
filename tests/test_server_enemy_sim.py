"""CS1 (server-authoritative pivot) -- the GATE test.

Proves the REAL Spawner + CombatUnit enemy simulation runs **headless** (dummy
SDL, no window) inside a server-side ServerLevel: an enemy spawns, acquires a
networked player target via the real entity quad tree, moves toward it, and a
melee hit resolves through the real InteractionResolver onto the target -- all
with zero rendering. If this passes, server-authoritative enemies are feasible
and CS2-CS5 are plumbing.
"""

import math
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
from Settings import TILESIZE  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_software_display():
    # Test isolation: an earlier module (test_render_backend) opens an OpenGL
    # display (set_mode(OPENGL|DOUBLEBUF)) and its dummy-SDL failures can leave
    # the display subsystem in a state where loading monster art via
    # convert_alpha SEGFAULTS. These tests construct REAL CombatUnits, so force a
    # clean SOFTWARE display before each one. (The real server runs in a fresh
    # process with no such pollution -- this is purely a shared-suite concern.)
    pygame.display.quit()
    pygame.display.init()
    pygame.display.set_mode((64, 64))
    yield


def _spawn_squid_with_player(player_xy, squid_tile=(10, 10)):
    level = ServerLevel(world_w=20000, world_h=20000)
    level.add_player_target("alice", x=player_xy[0], y=player_xy[1], health=100)
    enemy = level.spawn_enemy({"type": "squid", "pos": squid_tile})
    assert enemy is not None  # the server is the host now -> it DOES spawn
    return level, enemy


def test_enemy_spawns_headless_and_aggros_toward_player():
    # Squid at (10,10) tiles == (1500,1500)px; player 500px away, well inside the
    # squid's notice_radius (1000) -> it should aggro and close the distance.
    level, enemy = _spawn_squid_with_player(player_xy=(1500 + 500, 1500))

    def dist():
        ex, ey = enemy.rect.center
        return math.hypot((1500 + 500) - ex, 1500 - ey)

    d_start = dist()
    for _ in range(120):
        level.tick(1 / 60)
    d_end = dist()

    assert enemy.alive()
    assert d_end < d_start - 50  # the enemy meaningfully moved toward the player


def test_server_melee_callback_resolves_onto_target_headless():
    # The server's combat-context damage callback (== Level4.emit_enemy_melee_hit)
    # must route an enemy melee through the REAL InteractionResolver onto the
    # target, headless. Deterministic -- no dependence on attack cadence/timing.
    level, enemy = _spawn_squid_with_player(player_xy=(10 * TILESIZE + 40, 10 * TILESIZE))
    target = level.player_targets["alice"]
    level.emit_enemy_melee_hit(enemy, target, {"damage": 8, "type": "melee"})
    assert target.incoming_hits == [(8, "melee")]  # recorded for relay to the client


def test_enemy_lands_melee_through_the_full_tick_loop_headless():
    # The whole decide -> move -> execute_attack -> resolver chain through the real
    # tick loop, headless. We zero the attack cooldown so a hit lands inside the
    # fast test loop; the real server runs in real time where squid's 1500ms
    # cooldown applies naturally (see test above re: wall-clock cadence).
    level, enemy = _spawn_squid_with_player(player_xy=(10 * TILESIZE + 40, 10 * TILESIZE))
    target = level.player_targets["alice"]
    enemy.attack_cooldown = 0          # unthrottle for the test
    enemy.last_attack_action_time = 0

    for _ in range(30):
        level.tick(1 / 60)
        if target.incoming_hits:
            break

    assert target.incoming_hits, "enemy never landed a melee hit through the tick loop"
    amount, attack_type = target.incoming_hits[0]
    assert amount and amount > 0
    assert attack_type == "melee"


def test_server_projectile_travels_and_hits_player():
    # CS4b: a geometric server projectile aimed at a player travels straight and,
    # on overlap, records a hit (-> hit_player via drain_player_hits).
    level = ServerLevel(world_w=20000, world_h=20000)
    level.add_player_target("alice", x=200, y=200, health=100)
    target = level.player_targets["alice"]
    level.fire_projectile(enemy_pos=(120, 200), target_pos=(200, 200),
                          projectile_type="fireball", groups=[],
                          owner=None, source_team="enemy", amount=9)
    for _ in range(40):
        level.tick(1 / 60)
        if target.incoming_hits:
            break
    assert target.incoming_hits, "projectile never hit the player"
    assert target.incoming_hits[0] == (9, "magic")
    assert level.projectiles == []  # consumed on hit

    events = level.drain_player_hits()
    assert events and events[0]["type"] == "hit_player"
    assert events[0]["target_player_id"] == "alice" and events[0]["amount"] == 9


def test_server_projectile_expires_when_it_misses():
    level = ServerLevel(world_w=20000, world_h=20000)
    level.add_player_target("alice", x=200, y=2000, health=100)  # far off the line
    target = level.player_targets["alice"]
    level.fire_projectile(enemy_pos=(0, 0), target_pos=(100, 0),  # flies along y=0
                          projectile_type="fireball", groups=[],
                          owner=None, source_team="enemy", amount=9)
    for _ in range(200):
        level.tick(1 / 60)
    assert level.projectiles == []          # expired past max distance
    assert target.incoming_hits == []       # never hit


def test_dead_player_is_dropped_from_aggro():
    # A player reported at health 0 must be ignored by enemy targeting (so the
    # server stops swarming a downed client). The enemy should NOT close in.
    level, enemy = _spawn_squid_with_player(player_xy=(1500 + 500, 1500))
    level.update_player_target("alice", x=1500 + 500, y=1500, health=0)

    def dist():
        ex, ey = enemy.rect.center
        return math.hypot((1500 + 500) - ex, 1500 - ey)

    d_start = dist()
    for _ in range(120):
        level.tick(1 / 60)
    d_end = dist()

    # No valid target -> idle -> stays put (allow a tiny float drift).
    assert abs(d_end - d_start) < 5
