"""Two real clients, one server -- the headless proxy for Milestone 4.

Exercises the actual concurrency M4 is meant to shake out (two receiver
threads, two latched inputs, the tick loop as sole writer broadcasting to
both) without the GPU render path: two real MultiplayerClients connect, each
sends movement, and each must see the OTHER's server-authoritative position
and `status` change. The "two windows side by side" check stays a human test
(needs a real display); this proves everything up to the blit.
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

from network import MultiplayerClient, MSG_STATE_UPDATE  # noqa: E402
from server import GameServer  # noqa: E402

CHARACTER = "../Graphics/Orange_Wizard/"
DEADLINE = 5.0


@pytest.fixture
def server():
    srv = GameServer(host="127.0.0.1", port=0)
    port = srv.listen_socket.getsockname()[1]
    threading.Thread(target=srv.run, daemon=True).start()
    yield srv, port


def _latest_state(client):
    """Return the most recent state_update's players dict, draining the inbox."""
    latest = None
    for message in client.poll():
        if message["type"] == MSG_STATE_UPDATE:
            latest = message["players"]
    return latest


def _wait_for_player(client, pid):
    deadline = time.monotonic() + DEADLINE
    while time.monotonic() < deadline:
        players = _latest_state(client)
        if players and pid in players:
            return players[pid]
        time.sleep(0.01)
    raise AssertionError(f"{pid!r} never appeared in {client.player_id}'s state")


def _wait_until_seen_at(client, pid, x, y):
    """Wait until `client` sees `pid` at exactly (x, y) -- the cross-client invariant."""
    deadline = time.monotonic() + DEADLINE
    last = None
    while time.monotonic() < deadline:
        players = _latest_state(client)
        if players and pid in players:
            last = players[pid]
            if last["x"] == x and last["y"] == y:
                return last
        time.sleep(0.01)
    raise AssertionError(f"{client.player_id} never saw {pid} at ({x}, {y}); last={last}")


def test_each_client_sees_the_other_at_its_exact_reported_position(server):
    # THE invariant that actually matters (and that the old server-integration
    # tests failed to check): whatever position a client reports, the OTHER
    # client must see it there exactly -- no drift, no re-simulation.
    _srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join(CHARACTER, 100.0, 100.0)
    bob = MultiplayerClient("127.0.0.1", port, "bob")
    bob.send_join(CHARACTER, 900.0, 100.0)

    _wait_for_player(alice, "bob")
    _wait_for_player(bob, "alice")

    # alice "walks" right to a specific spot; bob "walks" down to another.
    alice.send_state(450.0, 100.0, 1.0, 0.0, False)
    bob.send_state(900.0, 700.0, 0.0, 1.0, False)

    # bob, as seen by alice, is exactly where bob said he is (+ correct facing).
    bob_seen = _wait_until_seen_at(alice, "bob", 900.0, 700.0)
    assert bob_seen["status"] == "down"
    # alice, as seen by bob, is exactly where alice said she is.
    alice_seen = _wait_until_seen_at(bob, "alice", 450.0, 100.0)
    assert alice_seen["status"] == "right"

    alice.close()
    bob.close()


def test_disconnect_is_visible_to_the_other_client(server):
    _srv, port = server
    alice = MultiplayerClient("127.0.0.1", port, "alice")
    alice.send_join(CHARACTER, 0.0, 0.0)
    bob = MultiplayerClient("127.0.0.1", port, "bob")
    bob.send_join(CHARACTER, 200.0, 0.0)

    _wait_for_player(alice, "bob")
    bob.close()

    deadline = time.monotonic() + DEADLINE
    gone = False
    while time.monotonic() < deadline:
        players = _latest_state(alice)
        if players is not None and "bob" not in players:
            gone = True
            break
        time.sleep(0.02)

    assert gone, "alice never saw bob disappear after bob disconnected"
    alice.close()
