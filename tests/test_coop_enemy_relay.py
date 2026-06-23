"""Co-op (Stage C) transport: enemy broadcast + host-directed hit routing.

CS2 (server-authoritative pivot): the SERVER owns the enemy sim. The first
client uploads the map's enemy spawn spec at join; the server builds a
ServerLevel from it and broadcasts the live enemy render-state to EVERY client
in state_update -- no client relays enemies, and a client-injected enemy list is
ignored. `host_id` is still assigned/broadcast (legacy C2/C2.5 routing) but no
longer decides who simulates.
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
    MSG_INPUT,
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


def test_first_joiner_is_host(server):
    _srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0)
    m = _wait_state(alice, lambda msg: msg.get("host_id") is not None)
    assert m["host_id"] == "alice"        # first to join owns the enemy sim
    alice.close()


def test_server_owns_and_broadcasts_enemies_to_all(server):
    _srv, port = server
    # The first client uploads the map's enemy spawn spec; the SERVER builds and
    # owns the enemy sim from it (no host relay).
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0,
                    enemy_spawns=[{"kind": "enemy", "type": "squid", "pos": [10, 10]}],
                    map_width=20000, map_height=20000)
    _wait_state(alice, lambda m: m.get("host_id") == "alice")

    bob = MultiplayerClient("127.0.0.1", port, "bob")
    bob.send_join("../Graphics/barb/", 50.0, 50.0)
    _wait(bob, MSG_PLAYER_JOINED)

    # BOTH clients receive the server-owned enemy in state_update.
    for client in (alice, bob):
        m = _wait_state(client, lambda msg: msg.get("enemies"))
        e = m["enemies"][0]
        assert e["type"] == "squid"
        assert set(e) >= {"id", "type", "x", "y", "status", "dir", "health"}
        assert e["health"] > 0
    alice.close()
    bob.close()


def test_server_spawns_from_uploaded_spawn_area(server):
    # The real MP level has NO placed enemies -- it spawns via proximity spawn
    # areas. This is the end-to-end fix: a client uploads its spawn areas, joins
    # near one, and the SERVER runs it + broadcasts the spawned enemies.
    _srv, port = server
    area = {
        "matrix": [[1]],
        "config": {"enemy_spawn_weights": {"squid": 1}, "frequency": 0,
                   "spawn_number": 2, "spawn_limit": 50},
        "object_info": {"anchor_tx": 10, "anchor_ty": 10, "x_pos": 10, "y_pos": 10,
                        "rect_x_px": 1500, "rect_y_px": 1500, "rect_w_px": 150,
                        "rect_h_px": 150, "object_id": 1},
    }
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join("../Graphics/Orange_Wizard/", 1520.0, 1520.0,  # near the area
                    spawn_areas=[area], map_width=20000, map_height=20000)

    m = _wait_state(alice, lambda msg: msg.get("enemies"))
    assert any(e["type"] == "squid" for e in m["enemies"])
    alice.close()


def test_client_injected_enemy_list_is_ignored(server):
    # Server-authoritative: no client may inject enemies. The client API no longer
    # exposes an `enemies` field, so we hand-craft a raw input carrying one
    # (a hacked client) and assert the server never broadcasts it.
    _srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0)
    _wait_state(alice, lambda m: m.get("host_id") == "alice")

    bob = MultiplayerClient("127.0.0.1", port, "bob")
    bob.send_join("../Graphics/barb/", 0.0, 0.0)
    _wait(bob, MSG_PLAYER_JOINED)

    bob._send({"type": MSG_INPUT, "player_id": "bob", "x": 0.0, "y": 0.0,
               "move_x": 0.0, "move_y": 0.0, "attacking": False,
               "enemies": [{"id": 99, "type": "squid", "x": 1, "y": 1,
                            "status": "idle", "dir": "right"}]})

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        for m in bob.poll():
            if m["type"] == MSG_STATE_UPDATE:
                assert all(e["id"] != 99 for e in m.get("enemies", [])), \
                    "server broadcast a client-injected enemy list"
        time.sleep(0.01)
    alice.close()
    bob.close()


def test_client_hit_damages_server_enemy(server):
    # CS3: a client's relayed hit_enemy is applied by the SERVER to its
    # authoritative enemy; the reduced health rides the broadcast back to all.
    _srv, port = server
    # Spawn alice FAR from the enemy so the squid never aggros/moves -- isolates
    # the health change to our hit.
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join("../Graphics/Orange_Wizard/", 5000.0, 5000.0,
                    enemy_spawns=[{"kind": "enemy", "type": "squid", "pos": [10, 10]}],
                    map_width=20000, map_height=20000)

    m = _wait_state(alice, lambda msg: msg.get("enemies"))
    enemy = m["enemies"][0]
    eid, hp0 = enemy["id"], enemy["health"]

    alice.send_hit_enemy(eid, 30.0, "weapon")

    def hp_dropped(msg):
        return any(e["id"] == eid and e["health"] <= hp0 - 30 for e in msg.get("enemies", []))

    _wait_state(alice, hp_dropped)  # the server applied the damage
    alice.close()


def test_lethal_hits_kill_server_enemy_and_remove_it(server):
    # Enough damage drops the enemy below 0 -> the server's check_death removes
    # it -> it disappears from the broadcast (clients then kill the puppet).
    _srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join("../Graphics/Orange_Wizard/", 5000.0, 5000.0,
                    enemy_spawns=[{"kind": "enemy", "type": "squid", "pos": [10, 10]}],
                    map_width=20000, map_height=20000)

    m = _wait_state(alice, lambda msg: msg.get("enemies"))
    eid = m["enemies"][0]["id"]
    hp = m["enemies"][0]["health"]

    # Squid i-frames gate one hit per ~vulnerability window; send several spaced
    # out so the cumulative damage is lethal.
    deadline = time.monotonic() + 5.0
    killed = False
    while time.monotonic() < deadline and not killed:
        alice.send_hit_enemy(eid, hp, "weapon")  # overkill each time
        for msg in alice.poll():
            if msg["type"] == MSG_STATE_UPDATE and all(e["id"] != eid for e in msg.get("enemies", [])):
                killed = True
                break
        time.sleep(0.05)
    assert killed, "server enemy was never removed after lethal damage"
    alice.close()
