"""Server-authoritative GameServer glue: the server runs the REAL Level4.

Drives GameServer._step_world_sim directly (no sockets, no real-time sleeps): it
lazily builds the real Level4 (which loads its own map + spawn areas), reconciles
the networked players from game_state, runs one real sim tick, and writes the
enemy render-state + reward/hit events back into game_state. The detailed sim
behavior (spawning, aggro, damage, death, loot) is covered in-process against the
real Level4 in test_server_players.py / test_headless_level.py; this file proves
the GameServer wires game_state <-> the level correctly.
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
pygame.display.set_mode((1280, 720))

from common import ServerPlayerState  # noqa: E402
from network import MSG_ENEMY_DIED, MSG_ITEM_REMOVED  # noqa: E402
import server as server_module  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_software_display():
    pygame.display.quit()
    pygame.display.init()
    pygame.display.set_mode((1280, 720))
    yield


def _server_with_player(x=0.0, y=0.0):
    # port=0 -> ephemeral bind; we never start the accept/sim threads, we drive
    # _step_world_sim by hand (each call advances the sim TICK_DT).
    srv = server_module.GameServer(host="127.0.0.1", port=0)
    srv.game_state.players["alice"] = ServerPlayerState(
        player_id="alice", character="../Graphics/Orange_Wizard/", x=x, y=y,
    )
    return srv


def _area0_center(srv):
    area = srv.server_level.layout_manager.spawner.spawn_areas[0]
    oi = area["object_info"]
    return (int(oi["rect_x_px"] + oi["rect_w_px"] / 2),
            int(oi["rect_y_px"] + oi["rect_h_px"] / 2))


def _move_player_onto_area0_and_spawn(srv, max_steps=560):
    """Build the level, park alice on enemy spawn area 0, and step until the real
    proximity area fires. Returns (cx, cy) once game_state.enemies is non-empty."""
    srv._step_world_sim()  # builds the real Level4 (alice present)
    cx, cy = _area0_center(srv)
    for _ in range(max_steps):
        srv.game_state.players["alice"].x = float(cx)
        srv.game_state.players["alice"].y = float(cy)
        srv._step_world_sim()
        if srv.game_state.enemies:
            return cx, cy
    raise AssertionError("real spawn area never fired at the networked player")


def test_server_builds_real_level_and_broadcasts_its_enemies():
    srv = _server_with_player()
    _move_player_onto_area0_and_spawn(srv)

    # The server loaded the REAL map (not an upload) and broadcasts its enemies.
    assert srv.server_level is not None
    assert len(srv.server_level.layout_manager.spawner.spawn_areas) > 0
    enemies = srv.game_state.enemies
    assert len(enemies) > 0
    e = enemies[0]
    assert set(e) >= {"id", "type", "x", "y", "status", "dir", "health"}
    assert e["health"] > 0


def test_server_idle_until_a_player_joins():
    # No players -> the server doesn't build/tick the level at all.
    srv = server_module.GameServer(host="127.0.0.1", port=0)
    srv._step_world_sim()
    assert srv.server_level is None
    assert srv.game_state.enemies == []


def test_pending_hit_damages_a_server_enemy():
    srv = _server_with_player()
    _move_player_onto_area0_and_spawn(srv)
    enemy = srv.game_state.enemies[0]
    eid, hp0 = enemy["id"], enemy["health"]

    # Queue a client's hit (as the receiver thread would) and step: the glue
    # drains pending_enemy_hits and applies it to the authoritative enemy.
    srv.game_state.pending_enemy_hits.append(
        {"enemy_id": eid, "amount": 40.0, "attack_type": "weapon"})
    srv._step_world_sim()

    after = next((e for e in srv.game_state.enemies if e["id"] == eid), None)
    assert after is None or after["health"] <= hp0 - 40  # damaged (or already dead)


def test_lethal_hit_removes_enemy_and_emits_enemy_died():
    srv = _server_with_player()
    _move_player_onto_area0_and_spawn(srv)
    enemy = srv.game_state.enemies[0]
    eid = enemy["id"]

    srv.game_state.pending_enemy_hits.append(
        {"enemy_id": eid, "amount": enemy["health"] + 1000, "attack_type": "weapon"})
    srv._step_world_sim()

    assert all(e["id"] != eid for e in srv.game_state.enemies)  # dropped from broadcast
    died = [ev for ev in srv.game_state.pending_events
            if ev.get("type") == MSG_ENEMY_DIED and ev.get("id") == eid]
    assert died, "no enemy_died event emitted for the lethal hit"


def test_pickup_claim_is_arbitrated_into_an_item_removed_event():
    srv = _server_with_player()
    srv._step_world_sim()  # build the level
    # Register a shared drop, then queue a client's claim (as the receiver would).
    srv.server_level._server_dropped_items[7] = {"item_id": "gold_coin", "x": 1, "y": 2}
    srv.game_state.pending_pickups.append({"drop_id": 7, "player_id": "alice"})
    srv._step_world_sim()

    removed = [ev for ev in srv.game_state.pending_events
               if ev.get("type") == MSG_ITEM_REMOVED and ev.get("drop_id") == 7]
    assert removed and removed[0]["to"] == "alice"
