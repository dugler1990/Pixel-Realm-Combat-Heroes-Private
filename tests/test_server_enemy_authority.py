"""CS2 (server-authoritative pivot) -- the server OWNS + broadcasts enemies.

Drives GameServer._step_enemy_sim directly (no sockets): once the first client
has uploaded an enemy spawn spec, the sim loop lazily builds a ServerLevel,
spawns those enemies, ticks them against the live player positions, and writes
their render-state into game_state.enemies (the exact shape clients' existing
_reconcile_enemy_puppets consumes). Proves the server is the enemy authority.
"""

import math
import os
import sys
from pathlib import Path
from types import SimpleNamespace

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

from Settings import TILESIZE  # noqa: E402
from common import ServerPlayerState  # noqa: E402
import server as server_module  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_software_display():
    # See test_server_enemy_sim: a prior OpenGL-display test can segfault the
    # real CombatUnit surface loads; force a clean software display per test.
    pygame.display.quit()
    pygame.display.init()
    pygame.display.set_mode((64, 64))
    yield


def _server_with_spawns(player_xy, squid_tile=(10, 10)):
    # port=0 -> ephemeral bind; we never run the accept/sim threads, we drive
    # _step_enemy_sim by hand.
    srv = server_module.GameServer(host="127.0.0.1", port=0)
    gs = srv.game_state
    gs.players["alice"] = ServerPlayerState(
        player_id="alice", character="../Graphics/Orange_Wizard/",
        x=float(player_xy[0]), y=float(player_xy[1]),
    )
    gs.pending_enemy_spawns = [{"kind": "enemy", "type": "squid", "pos": list(squid_tile)}]
    gs.map_width = 20000.0
    gs.map_height = 20000.0
    return srv


def _enemy_spawn_area(tile=(10, 10)):
    ax, ay = tile
    return {
        "matrix": [[1]],
        "config": {"enemy_spawn_weights": {"squid": 1}, "spawn_type": "random_weights",
                   "frequency": 0, "spawn_number": 2, "spawn_limit": 50},
        "object_info": {"anchor_tx": ax, "anchor_ty": ay, "x_pos": ax, "y_pos": ay,
                        "rect_x_px": ax * TILESIZE, "rect_y_px": ay * TILESIZE,
                        "rect_w_px": TILESIZE, "rect_h_px": TILESIZE, "object_id": 1},
    }


def test_server_spawns_enemies_from_spawn_areas():
    # The MP level has NO placed enemies -- it spawns via proximity spawn areas.
    # The server must run those areas itself (the whole point of this fix).
    srv = server_module.GameServer(host="127.0.0.1", port=0)
    gs = srv.game_state
    gs.players["alice"] = ServerPlayerState(
        player_id="alice", character="x", x=10 * TILESIZE + 20, y=10 * TILESIZE + 20)
    gs.pending_enemy_spawns = []                      # no placed enemies
    gs.pending_spawn_areas = [_enemy_spawn_area((10, 10))]
    gs.map_width = gs.map_height = 20000.0

    srv._step_enemy_sim()                            # build + register areas + first tick
    assert srv.server_level is not None
    assert srv.server_level.spawner.spawn_areas       # the area registered
    assert len(srv.game_state.enemies) >= 1           # produced enemies near the player
    assert all(e["type"] == "squid" for e in srv.game_state.enemies)


def test_server_spawn_area_gated_by_player_proximity():
    # No player anywhere near the area -> nothing spawns (proximity gate).
    srv = server_module.GameServer(host="127.0.0.1", port=0)
    gs = srv.game_state
    gs.players["alice"] = ServerPlayerState(
        player_id="alice", character="x", x=18000.0, y=18000.0)  # far away
    gs.pending_spawn_areas = [_enemy_spawn_area((10, 10))]
    gs.map_width = gs.map_height = 20000.0
    for _ in range(5):
        srv._step_enemy_sim()
    assert srv.game_state.enemies == []


def test_server_builds_sim_and_broadcasts_enemy_state():
    srv = _server_with_spawns(player_xy=(10 * TILESIZE + 500, 10 * TILESIZE))
    srv._step_enemy_sim()

    assert srv.server_level is not None              # lazily built from the spec
    assert len(srv.game_state.enemies) == 1
    e = srv.game_state.enemies[0]
    assert e["type"] == "squid"
    assert set(e) >= {"id", "type", "x", "y", "status", "dir", "health"}  # puppet shape
    assert e["health"] > 0


def test_server_enemy_aggros_player_over_ticks():
    srv = _server_with_spawns(player_xy=(10 * TILESIZE + 500, 10 * TILESIZE))

    def enemy_dist():
        e = srv.game_state.enemies[0]
        return math.hypot((10 * TILESIZE + 500) - e["x"], (10 * TILESIZE) - e["y"])

    srv._step_enemy_sim()
    d_start = enemy_dist()
    for _ in range(120):
        srv._step_enemy_sim()
    d_end = enemy_dist()
    assert d_end < d_start - 50  # server-owned enemy moved toward the player


def test_server_sim_idle_until_spawn_spec_uploaded():
    srv = server_module.GameServer(host="127.0.0.1", port=0)
    srv.game_state.players["alice"] = ServerPlayerState(
        player_id="alice", character="x", x=0.0, y=0.0,
    )
    srv._step_enemy_sim()  # no pending_enemy_spawns yet
    assert srv.server_level is None
    assert srv.game_state.enemies == []


def test_server_drops_enemies_for_departed_players_targeting():
    # Spawn, let it aggro, then remove the player -> target list empties; the sim
    # keeps running (enemy still broadcast) but has no one to chase.
    srv = _server_with_spawns(player_xy=(10 * TILESIZE + 300, 10 * TILESIZE))
    srv._step_enemy_sim()
    assert srv.server_level.player_targets  # alice is a target
    srv.game_state.players.clear()
    srv._step_enemy_sim()
    assert srv.server_level.player_targets == {}     # target reconciled away
    assert len(srv.game_state.enemies) == 1          # enemy still owned/broadcast


def test_drain_player_hits_emits_hit_player_event_and_clears():
    # CS4: a recorded enemy->player hit becomes a hit_player broadcast event.
    srv = _server_with_spawns(player_xy=(10 * TILESIZE + 40, 10 * TILESIZE))
    srv._step_enemy_sim()  # build + register the target
    target = srv.server_level.player_targets["alice"]
    target.incoming_hits.append((8, "melee"))
    events = srv.server_level.drain_player_hits()
    assert events == [{"type": "hit_player", "target_player_id": "alice",
                       "amount": 8, "attack_type": "melee"}]
    assert target.incoming_hits == []


def test_enemy_melee_emits_hit_player_through_the_sim():
    # Full server path: enemy on the player + zeroed cooldown -> a melee lands ->
    # _step_enemy_sim queues a hit_player into pending_events (the broadcast queue).
    srv = _server_with_spawns(player_xy=(10 * TILESIZE + 40, 10 * TILESIZE))
    srv._step_enemy_sim()
    enemy = srv.server_level.spawner.enemies[0]
    enemy.attack_cooldown = 0
    enemy.last_attack_action_time = 0

    got = False
    for _ in range(30):
        srv._step_enemy_sim()
        if any(e.get("type") == "hit_player" for e in srv.game_state.pending_events):
            got = True
            break
    assert got, "enemy melee never produced a hit_player broadcast event"
    hp = next(e for e in srv.game_state.pending_events if e.get("type") == "hit_player")
    assert hp["target_player_id"] == "alice" and hp["amount"] > 0


def test_drain_deaths_emits_enemy_died_event_and_clears():
    srv = _server_with_spawns(player_xy=(10 * TILESIZE + 300, 10 * TILESIZE))
    srv._step_enemy_sim()  # build
    srv.server_level.pending_deaths.append(
        {"id": 5, "x": 1, "y": 2, "monster": "squid", "exp": 3}
    )
    events = srv.server_level.drain_deaths()
    assert events == [{"type": "enemy_died", "id": 5, "x": 1, "y": 2,
                       "monster": "squid", "exp": 3}]
    assert srv.server_level.pending_deaths == []


def test_lethal_hit_emits_enemy_died_and_removes_enemy():
    # CS5a: a server-applied lethal hit -> the enemy dies -> _step_enemy_sim emits
    # an enemy_died broadcast event AND drops the enemy from the relay.
    srv = _server_with_spawns(player_xy=(10 * TILESIZE + 300, 10 * TILESIZE))
    srv._step_enemy_sim()
    enemy = srv.server_level.spawner.enemies[0]
    srv.game_state.pending_enemy_hits.append(
        {"type": "hit_enemy", "player_id": "alice", "enemy_id": enemy.id,
         "amount": enemy.health + 50, "attack_type": "weapon"}
    )
    srv._step_enemy_sim()

    died = [e for e in srv.game_state.pending_events if e.get("type") == "enemy_died"]
    assert len(died) == 1
    assert died[0]["id"] == enemy.id and died[0]["monster"] == "squid"
    assert "exp" in died[0]
    assert all(e["id"] != enemy.id for e in srv.game_state.enemies)  # removed from relay


def test_roll_and_register_drops_emits_item_dropped_with_exact_gold():
    # CS5b: the server rolls loot headlessly (no Item objects), registers each
    # drop with a stable drop_id, and queues item_dropped events -- gold carries
    # the exact rolled amount.
    srv = _server_with_spawns(player_xy=(10 * TILESIZE + 300, 10 * TILESIZE))
    srv._step_enemy_sim()
    level = srv.server_level
    enemy = SimpleNamespace(
        rect=pygame.Rect(100, 200, 10, 10),
        item_drop_info={
            "guaranteed_drops": [{"item_id": "health_potion", "quantity": 1}],
            "gold_drop": {"chance": 1.0, "min": 5, "max": 5},
        },
    )
    level._roll_and_register_drops(enemy)
    events = level.drain_item_drops()

    ids = {e["item_id"] for e in events}
    assert "health_potion" in ids and "gold_coin" in ids
    gold_ev = next(e for e in events if e["item_id"] == "gold_coin")
    assert gold_ev["gold"] == 5
    assert all(e["type"] == "item_dropped" and "drop_id" in e for e in events)
    assert len(level.dropped_items) == 2          # registered for pickup
    assert level.drain_item_drops() == []          # drained


def test_arbitrate_pickup_first_claim_wins():
    srv = _server_with_spawns(player_xy=(10 * TILESIZE + 300, 10 * TILESIZE))
    srv._step_enemy_sim()
    level = srv.server_level
    level.dropped_items[42] = {"item_id": "health_potion", "x": 1, "y": 2}

    ev = level.arbitrate_pickup(42, "bob")
    assert ev == {"type": "item_removed", "drop_id": 42, "to": "bob"}
    assert 42 not in level.dropped_items
    assert level.arbitrate_pickup(42, "alice") is None   # already claimed -> no double-grant


def test_player_reported_dead_is_dropped_from_server_aggro():
    # CS4 health relay: a player whose relayed health is 0 must be ignored by the
    # server's enemy aggro (target removed from the entity tree).
    srv = _server_with_spawns(player_xy=(10 * TILESIZE + 300, 10 * TILESIZE))
    srv.game_state.players["alice"].health = 0.0
    srv._step_enemy_sim()
    # target exists but health 0 -> enemy can't validly aggro it
    enemy = srv.server_level.spawner.enemies[0]
    target = srv.server_level.player_targets["alice"]
    assert target.health == 0
    assert not enemy._is_valid_aggro_target(target)
