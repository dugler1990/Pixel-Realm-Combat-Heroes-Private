"""Integration test for Code/network/client.py (Milestone 2).

Exercises `MultiplayerClient` against the real `GameServer` over TCP --
the "does the real client correctly drive outbound/inbound messages" half
of the multiplayer plan's Verification step 2, independent of
pygame/rendering (which Milestone 3 covers via RemotePlayer).
"""

import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT / "Server", REPO_ROOT / "Code"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from network.client import MultiplayerClient  # noqa: E402
from network.protocol import MSG_PLAYER_JOINED, MSG_STATE_UPDATE  # noqa: E402
from server import GameServer  # noqa: E402

WAIT_TIMEOUT = 5.0


@pytest.fixture
def server():
    srv = GameServer(host="127.0.0.1", port=0, run_world_sim=False)
    port = srv.listen_socket.getsockname()[1]
    threading.Thread(target=srv.run, daemon=True).start()
    return srv, port


def _wait_for(client, msg_type, timeout=WAIT_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for message in client.poll():
            if message["type"] == msg_type:
                return message
        time.sleep(0.01)
    raise TimeoutError(f"never received {msg_type!r}")


def test_join_is_visible_on_server_and_client(server):
    srv, port = server
    client = MultiplayerClient("127.0.0.1", port, "alice")
    client.send_join("../Graphics/Orange_Wizard/", 100.0, 150.0)

    joined = _wait_for(client, MSG_PLAYER_JOINED)
    assert joined["player_id"] == "alice"
    assert joined["character"] == "../Graphics/Orange_Wizard/"

    with srv.game_state.lock:
        assert "alice" in srv.game_state.players
        assert srv.game_state.players["alice"].x == 100.0

    client.close()


def test_send_state_relays_position_to_server(server):
    srv, port = server
    client = MultiplayerClient("127.0.0.1", port, "bob")
    client.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0)
    _wait_for(client, MSG_PLAYER_JOINED)

    client.send_state(640.0, 480.0, 1.0, 0.0, False)

    deadline = time.monotonic() + WAIT_TIMEOUT
    relayed = False
    while time.monotonic() < deadline and not relayed:
        for message in client.poll():
            if message["type"] != MSG_STATE_UPDATE:
                continue
            snapshot = message["players"]["bob"]
            if snapshot["x"] == 640.0 and snapshot["status"] == "right":
                relayed = True
                break
        time.sleep(0.01)

    assert relayed

    with srv.game_state.lock:
        # stored exactly as reported (relay), not re-simulated
        assert srv.game_state.players["bob"].x == 640.0
        assert srv.game_state.players["bob"].y == 480.0

    client.close()


def test_close_sends_leave_and_server_removes_player(server):
    srv, port = server
    client = MultiplayerClient("127.0.0.1", port, "carol")
    client.send_join("../Graphics/Orange_Wizard/", 0.0, 0.0)
    _wait_for(client, MSG_PLAYER_JOINED)

    client.close()

    deadline = time.monotonic() + WAIT_TIMEOUT
    while time.monotonic() < deadline:
        with srv.game_state.lock:
            if "carol" not in srv.game_state.players:
                break
        time.sleep(0.01)

    with srv.game_state.lock:
        assert "carol" not in srv.game_state.players
