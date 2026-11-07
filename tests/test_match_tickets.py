"""The match server's front door: signed tickets, the join gate, and the pre-join limits.

Real GameServer over real TCP, like test_multiplayer_server.py. run_world_sim=False: the
gate does not depend on the level. exit_when_done stays False (os._exit would kill pytest).
"""

import socket
import struct
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT / "Server", REPO_ROOT / "Code"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import tickets  # noqa: E402
from network.protocol import (  # noqa: E402
    MSG_JOIN,
    MSG_JOIN_REJECTED,
    MSG_PICKUP_ITEM,
    MSG_STATE_UPDATE,
    PROTOCOL_VERSION,
    pack_message,
    recv_message,
)
from server import GameServer  # noqa: E402

SECRET = bytes(range(32))
MATCH_ID = "m1"
WIZARD = "../Graphics/Orange_Wizard/"


def _ticket(user_id="u-1", match_id=MATCH_ID, ttl=60.0, secret=SECRET):
    return tickets.mint(secret, match_id, user_id, "alice", WIZARD, ttl)


@pytest.fixture
def match_server():
    srv = GameServer(host="127.0.0.1", port=0, run_world_sim=False,
                     match_id=MATCH_ID, ticket_secret=SECRET)
    port = srv.listen_socket.getsockname()[1]
    threading.Thread(target=srv.run, daemon=True).start()
    return srv, port


def _connect(port, timeout=5.0):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", port))
    sock.settimeout(timeout)
    return sock


def _join(sock, ticket=None, protocol=PROTOCOL_VERSION, player_id="liar", character="../Graphics/barb/"):
    message = {"type": MSG_JOIN, "player_id": player_id, "character": character, "x": 0.0, "y": 0.0}
    if protocol is not None:
        message["protocol"] = protocol
    if ticket is not None:
        message["ticket"] = ticket
    sock.sendall(pack_message(message))


def _recv_until(sock, msg_type, predicate=lambda m: True):
    while True:
        message = recv_message(sock)
        if message["type"] == msg_type and predicate(message):
            return message


def _assert_closed(sock):
    """The server closed its end: the next read sees EOF (or a reset)."""
    try:
        assert sock.recv(1) == b""
    except ConnectionError:
        pass


# -- tickets on their own --

def test_ticket_round_trips():
    payload = tickets.verify(SECRET, _ticket(), MATCH_ID)
    assert payload["uid"] == "u-1"
    assert payload["chr"] == WIZARD


@pytest.mark.parametrize("bad", [
    "garbage",
    None,
    12345,
    "x.y.z",
])
def test_malformed_tickets_are_refused(bad):
    with pytest.raises(tickets.TicketError):
        tickets.verify(SECRET, bad, MATCH_ID)


def test_tampered_expired_and_foreign_tickets_are_refused():
    body, sig = _ticket().split(".")
    other_body = _ticket(user_id="u-2").split(".")[0]
    with pytest.raises(tickets.TicketError, match="signature"):
        tickets.verify(SECRET, other_body + "." + sig, MATCH_ID)
    with pytest.raises(tickets.TicketError, match="signature"):
        tickets.verify(SECRET, body + "." + sig[:-2] + "AA", MATCH_ID)
    with pytest.raises(tickets.TicketError, match="signature"):
        tickets.verify(bytes(32), _ticket(), MATCH_ID)
    with pytest.raises(tickets.TicketError, match="another match"):
        tickets.verify(SECRET, _ticket(match_id="m2"), MATCH_ID)
    with pytest.raises(tickets.TicketError, match="expired"):
        tickets.verify(SECRET, _ticket(ttl=-1), MATCH_ID)


def test_short_secret_is_refused():
    with pytest.raises(ValueError):
        tickets.secret_from_env("ab" * 16)


# -- the join gate --

def test_open_mode_refuses_a_public_address():
    with pytest.raises(ValueError):
        GameServer(host="0.0.0.0", port=0, run_world_sim=False)


def test_valid_ticket_joins_under_the_ticket_identity(match_server):
    _, port = match_server
    sock = _connect(port)
    _join(sock, ticket=_ticket())
    state = _recv_until(sock, MSG_STATE_UPDATE, lambda m: m["players"])
    assert list(state["players"]) == ["u-1"]
    assert state["players"]["u-1"]["character"] == WIZARD
    sock.close()


@pytest.mark.parametrize("ticket,protocol", [
    ("not.a-ticket", PROTOCOL_VERSION),
    (None, PROTOCOL_VERSION),
    ("valid", PROTOCOL_VERSION - 1),
    ("valid", None),
    ("expired", PROTOCOL_VERSION),
])
def test_bad_joins_are_rejected_and_closed(match_server, ticket, protocol):
    srv, port = match_server
    if ticket == "valid":
        ticket = _ticket()
    elif ticket == "expired":
        ticket = _ticket(ttl=-1)
    sock = _connect(port)
    _join(sock, ticket=ticket, protocol=protocol)
    reply = recv_message(sock)
    assert reply["type"] == MSG_JOIN_REJECTED
    assert reply["reason"]
    _assert_closed(sock)
    assert srv.game_state.players == {}


def test_second_join_with_the_same_ticket_is_rejected(match_server):
    srv, port = match_server
    first = _connect(port)
    _join(first, ticket=_ticket())
    _recv_until(first, MSG_STATE_UPDATE, lambda m: m["players"])
    second = _connect(port)
    _join(second, ticket=_ticket())
    reply = recv_message(second)
    assert reply["type"] == MSG_JOIN_REJECTED
    _assert_closed(second)
    # The first connection is untouched.
    time.sleep(0.2)
    assert list(srv.game_state.players) == ["u-1"]
    first.close()


# -- before the join --

def test_a_silent_connection_is_dropped(match_server):
    _, port = match_server
    sock = _connect(port, timeout=10.0)
    started = time.monotonic()
    _assert_closed(sock)
    assert time.monotonic() - started < 9.0


def test_an_oversized_frame_closes_the_connection(match_server):
    _, port = match_server
    sock = _connect(port)
    sock.sendall(struct.pack(">I", 10 * 1024 * 1024) + b"x" * 16)
    _assert_closed(sock)


def test_loot_claims_carry_the_senders_own_id(match_server):
    srv, port = match_server
    sock = _connect(port)
    _join(sock, ticket=_ticket())
    _recv_until(sock, MSG_STATE_UPDATE, lambda m: m["players"])
    sock.sendall(pack_message({"type": MSG_PICKUP_ITEM, "player_id": "someone-else", "drop_id": 7}))
    deadline = time.monotonic() + 3
    while not srv.game_state.pending_pickups and time.monotonic() < deadline:
        time.sleep(0.02)
    assert srv.game_state.pending_pickups == [
        {"type": MSG_PICKUP_ITEM, "player_id": "u-1", "drop_id": 7}
    ]
    sock.close()
