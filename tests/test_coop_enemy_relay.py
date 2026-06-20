"""Co-op (Stage C, C1) transport: host role + enemy state relay.

The server assigns `host` to the first joiner and broadcasts `host_id` so every
client learns its role. The host relays its live enemy render state in the
per-frame message; the server stores ONLY the host's list and rebroadcasts it in
state_update (it never simulates enemies). Covers role assignment, the host->
joiner enemy relay, and that a non-host's enemy list is ignored.
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
    MSG_HIT_ENEMY,
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


def test_host_enemies_relayed_to_joiner(server):
    _srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")  # host
    alice.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0)
    _wait_state(alice, lambda m: m.get("host_id") == "alice")

    bob = MultiplayerClient("127.0.0.1", port, "bob")      # joiner
    bob.send_join("../Graphics/barb/", 50.0, 50.0)
    _wait(bob, MSG_PLAYER_JOINED)

    enemies = [{"id": 7, "type": "squid", "x": 120, "y": 80,
                "status": "move", "dir": "left", "health": 30}]
    alice.send_state(0.0, 0.0, 0.0, 0.0, False, enemies=enemies)

    m = _wait_state(bob, lambda msg: msg.get("enemies"))
    assert m["host_id"] == "alice"
    e = m["enemies"][0]
    assert e["id"] == 7 and e["type"] == "squid"
    assert (e["x"], e["y"]) == (120, 80)
    assert e["status"] == "move" and e["dir"] == "left"
    alice.close()
    bob.close()


def test_non_host_enemy_list_is_ignored(server):
    _srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")  # host (sends no enemies)
    alice.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0)
    _wait_state(alice, lambda m: m.get("host_id") == "alice")

    bob = MultiplayerClient("127.0.0.1", port, "bob")      # joiner
    bob.send_join("../Graphics/barb/", 0.0, 0.0)
    _wait(bob, MSG_PLAYER_JOINED)

    # A non-host that (wrongly) sends enemies must NOT have them relayed.
    bob.send_state(0.0, 0.0, 0.0, 0.0, False,
                   enemies=[{"id": 99, "type": "squid", "x": 1, "y": 1,
                             "status": "idle", "dir": "right"}])

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        for m in bob.poll():
            if m["type"] == MSG_STATE_UPDATE:
                assert all(e["id"] != 99 for e in m.get("enemies", [])), \
                    "server relayed a non-host client's enemy list"
        time.sleep(0.01)
    alice.close()
    bob.close()


def test_joiner_hit_relayed_to_host_only(server):
    _srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")  # host
    alice.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0)
    _wait_state(alice, lambda m: m.get("host_id") == "alice")

    bob = MultiplayerClient("127.0.0.1", port, "bob")      # joiner
    bob.send_join("../Graphics/barb/", 0.0, 0.0)
    _wait(bob, MSG_PLAYER_JOINED)

    bob.send_hit_enemy(7, 15.0, "weapon")

    # The host receives the damage event...
    m = _wait(alice, MSG_HIT_ENEMY)
    assert m["enemy_id"] == 7 and m["amount"] == 15.0 and m["attack_type"] == "weapon"
    assert m["player_id"] == "bob"

    # ...and the joiner does NOT (it's forwarded to the host only).
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        for mm in bob.poll():
            assert mm["type"] != MSG_HIT_ENEMY, "joiner received the hit it sent"
        time.sleep(0.01)
    alice.close()
    bob.close()
