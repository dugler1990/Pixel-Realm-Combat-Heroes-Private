"""Integration test for the headless multiplayer server (Milestone 1).

Exercises Server/server.py + Server/common.py + Code/network/protocol.py
end to end over real TCP sockets, with no pygame client involved -- the
"server in isolation" verification step from the multiplayer plan.
"""

import socket
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT / "Server", REPO_ROOT / "Code"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from network.protocol import (  # noqa: E402
    MSG_INPUT,
    MSG_JOIN,
    MSG_LEAVE,
    MSG_PLAYER_JOINED,
    MSG_PLAYER_LEFT,
    MSG_STATE_UPDATE,
    pack_message,
    recv_message,
)
from server import GameServer  # noqa: E402

SOCKET_TIMEOUT = 5.0


@pytest.fixture
def server():
    srv = GameServer(host="127.0.0.1", port=0)
    port = srv.listen_socket.getsockname()[1]
    threading.Thread(target=srv.run, daemon=True).start()
    return srv, port


def _connect(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", port))
    sock.settimeout(SOCKET_TIMEOUT)
    return sock


def _join(sock, player_id, character="../Graphics/Orange_Wizard/", x=0.0, y=0.0):
    sock.sendall(pack_message({
        "type": MSG_JOIN, "player_id": player_id, "character": character, "x": x, "y": y,
    }))


def _recv_until(sock, msg_type):
    while True:
        message = recv_message(sock)
        if message["type"] == msg_type:
            return message


def test_join_broadcasts_player_joined(server):
    _srv, port = server
    sock = _connect(port)
    _join(sock, "alice", x=100.0, y=150.0)

    joined = _recv_until(sock, MSG_PLAYER_JOINED)
    assert joined["player_id"] == "alice"
    assert joined["character"] == "../Graphics/Orange_Wizard/"
    assert joined["x"] == 100.0
    assert joined["y"] == 150.0


def test_state_update_rate_is_roughly_60hz(server):
    _srv, port = server
    sock = _connect(port)
    _join(sock, "bob")
    _recv_until(sock, MSG_PLAYER_JOINED)

    timestamps = []
    for _ in range(20):
        _recv_until(sock, MSG_STATE_UPDATE)
        timestamps.append(time.monotonic())

    intervals = [b - a for a, b in zip(timestamps, timestamps[1:])]
    avg_interval = sum(intervals) / len(intervals)
    assert 0.008 < avg_interval < 0.04  # ~16.7ms at 60Hz, generous tolerance


def test_input_relays_position_verbatim_and_derives_status(server):
    # v0 is a position RELAY: the server stores the client-reported (x, y)
    # exactly (no server-side integration) and derives `status` from the inputs.
    _srv, port = server
    sock = _connect(port)
    _join(sock, "carol", x=0.0, y=0.0)
    _recv_until(sock, MSG_PLAYER_JOINED)

    sock.sendall(pack_message({
        "type": MSG_INPUT, "player_id": "carol",
        "x": 777.0, "y": 888.0, "move_x": 1.0, "move_y": 0.0, "attacking": False,
    }))

    state = _recv_until(sock, MSG_STATE_UPDATE)
    while "carol" not in state["players"] or state["players"]["carol"]["x"] != 777.0:
        state = _recv_until(sock, MSG_STATE_UPDATE)

    snap = state["players"]["carol"]
    assert snap["x"] == 777.0  # relayed verbatim, NOT integrated from input
    assert snap["y"] == 888.0
    assert snap["status"] == "right"
    assert snap["direction_x"] == 1.0


def test_second_client_join_and_leave_are_visible_to_first(server):
    _srv, port = server
    alice = _connect(port)
    _join(alice, "alice", x=0.0, y=0.0)
    _recv_until(alice, MSG_PLAYER_JOINED)  # alice's own join notice

    bob = _connect(port)
    _join(bob, "bob", x=50.0, y=50.0)

    joined = _recv_until(alice, MSG_PLAYER_JOINED)
    assert joined["player_id"] == "bob"

    state = _recv_until(alice, MSG_STATE_UPDATE)
    assert set(state["players"].keys()) == {"alice", "bob"}

    bob.sendall(pack_message({"type": MSG_LEAVE, "player_id": "bob"}))
    bob.close()

    left = _recv_until(alice, MSG_PLAYER_LEFT)
    assert left["player_id"] == "bob"

    state = _recv_until(alice, MSG_STATE_UPDATE)
    assert set(state["players"].keys()) == {"alice"}
