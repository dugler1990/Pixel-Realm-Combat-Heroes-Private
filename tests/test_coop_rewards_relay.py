"""Co-op (CS5) transport: SERVER-emitted rewards + server-arbitrated loot.

Server-authoritative pivot: the SERVER owns deaths/loot. On a lethal hit it
broadcasts enemy_died (+ any rolled item_dropped) to EVERY client; it arbitrates
pickups (first claim wins) and broadcasts item_removed{to}. Clients cannot inject
reward events. Real sockets, mirroring test_coop_enemy_relay's setup.
"""

import os
import sys
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT / "Server", REPO_ROOT / "Code"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from network import (  # noqa: E402
    MultiplayerClient,
    MSG_ENEMY_DIED,
    MSG_ITEM_DROPPED,
    MSG_ITEM_REMOVED,
    MSG_PLAYER_JOINED,
    MSG_STATE_UPDATE,
)
from server import GameServer  # noqa: E402


@pytest.fixture
def server():
    srv = GameServer(host="127.0.0.1", port=0)
    port = srv.listen_socket.getsockname()[1]
    threading.Thread(target=srv.run, daemon=True).start()
    yield srv, port


def _wait(client, msg_type, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for m in client.poll():
            if m["type"] == msg_type:
                return m
        time.sleep(0.01)
    raise AssertionError(f"never received {msg_type}")


def _wait_state(client, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for m in client.poll():
            if m["type"] == MSG_STATE_UPDATE and predicate(m):
                return m
        time.sleep(0.01)
    raise AssertionError("no state_update satisfied the predicate")


def _collect(client, timeout=2.0):
    # Accumulate ALL messages over a window (a single poll() drains the queue, so
    # waiting for one type would discard co-arriving events like enemy_died+drop).
    out = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        out.extend(client.poll())
        time.sleep(0.01)
    return out


def _two_players_with_enemy(port, drop_info=None):
    # Players spawn FAR from the enemy so it never aggros/moves -- it only dies
    # from our hit. Optional drop_info forces deterministic loot.
    spawn = {"kind": "enemy", "type": "squid", "pos": [10, 10]}
    if drop_info is not None:
        spawn["item_drop_info"] = drop_info
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join("../Graphics/Orange_Wizard/", 5000.0, 5000.0,
                    enemy_spawns=[spawn], map_width=20000, map_height=20000)
    _wait_state(alice, lambda m: m.get("host_id") == "alice")
    bob = MultiplayerClient("127.0.0.1", port, "bob")
    bob.send_join("../Graphics/barb/", 5200.0, 5000.0)
    _wait(bob, MSG_PLAYER_JOINED)
    m = _wait_state(alice, lambda msg: msg.get("enemies"))
    enemy = m["enemies"][0]
    return alice, bob, enemy["id"], enemy["health"]


def test_lethal_hit_broadcasts_enemy_died_to_both(server):
    _srv, port = server
    alice, bob, eid, hp = _two_players_with_enemy(port)
    alice.send_hit_enemy(eid, hp + 50, "weapon")

    for client in (alice, bob):
        died = [m for m in _collect(client) if m["type"] == MSG_ENEMY_DIED and m["id"] == eid]
        assert died, "client never received the server's enemy_died"
        assert died[0]["monster"] == "squid"
    alice.close()
    bob.close()


def test_client_cannot_inject_reward_event(server):
    _srv, port = server
    alice, bob, eid, hp = _two_players_with_enemy(port)
    # bob hand-crafts an enemy_died (a hacked client) -> the server must NOT relay it.
    bob._send({"type": MSG_ENEMY_DIED, "player_id": "bob", "id": 99,
               "x": 1, "y": 1, "monster": "x", "exp": 99})
    injected = [m for m in _collect(alice) if m["type"] == MSG_ENEMY_DIED and m["id"] == 99]
    assert not injected, "server broadcast a client-injected death event"
    alice.close()
    bob.close()


def test_server_drops_loot_and_arbitrates_pickup(server):
    _srv, port = server
    alice, bob, eid, hp = _two_players_with_enemy(
        port, drop_info={"gold_drop": {"chance": 1.0, "min": 7, "max": 7}})
    alice.send_hit_enemy(eid, hp + 50, "weapon")

    # The server rolls the (guaranteed) gold drop and broadcasts item_dropped to both.
    drops = [m for m in _collect(alice) if m["type"] == MSG_ITEM_DROPPED]
    assert drops, "server never broadcast the loot drop"
    drop = drops[0]
    assert drop["item_id"] == "gold_coin" and drop.get("gold") == 7  # exact rolled amount
    drop_id = drop["drop_id"]

    # bob claims it -> the server awards it to bob (item_removed{to: bob}) for all.
    bob.send_pickup_item(drop_id)
    removed = [m for m in _collect(bob)
               if m["type"] == MSG_ITEM_REMOVED and m["drop_id"] == drop_id]
    assert removed, "server never broadcast the pickup award"
    assert removed[0]["to"] == "bob"
    alice.close()
    bob.close()
