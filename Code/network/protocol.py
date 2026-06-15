"""Shared wire protocol for the rudimentary multiplayer server/client.

Pure `struct` + `msgpack` + plain dicts. No pygame or other game imports,
so this module is importable from both the headless `Server/` process and
the real game client under `Code/`.

Framing: every message is `[4-byte big-endian length][msgpack payload]`.

Message shapes (see the multiplayer plan's "Wire protocol" section):

    # client -> server, ~once per local frame. Carries the client's ACTUAL
    # local position (x, y -- sprite center, from Entity.move()) plus its
    # movement direction + attacking. v0 is a position RELAY: the client owns
    # its own position (plan ownership table), the server stores x/y verbatim
    # and only derives the animation `status` from move_x/move_y/attacking.
    # (We deliberately do NOT re-integrate position server-side in v0 -- that
    # caused large drift vs the client's real Entity.move physics. Server-side
    # authoritative position is Stage B+.)
    {"type": "input", "player_id": "...", "seq": 142,
     "x": 1234.0, "y": 5678.0,
     "move_x": -1.0, "move_y": 0.0, "attacking": False}

    # client -> server, on connect / disconnect. Stage B optionally adds the
    # player's collision-rect size (hitbox_w/h) and a one-time upload of the
    # map's obstacle rects + dimensions (the client already has them) so the
    # server can build a quadtree and validate positions against walls. All
    # optional -- omitting them yields the plain v0 relay (no server collision).
    {"type": "join", "player_id": "...", "character": "../Graphics/Orange_Wizard/",
     "x": ..., "y": ...,
     "hitbox_w": .., "hitbox_h": ..,
     "obstacles": [[x, y, w, h], ...], "map_width": .., "map_height": ..}
    {"type": "leave", "player_id": "..."}

    # server -> client, broadcast at tick rate (includes the receiver's own entry)
    {"type": "state_update", "tick": 4821, "server_time_ms": 1234567.8,
     "players": {"<id>": {"character": "...", "x": .., "y": ..,
                           "direction_x": .., "direction_y": .., "status": "left"}}}

    # server -> client, lifecycle notices
    {"type": "player_joined", "player_id": "...", "character": "...", "x": .., "y": ..}
    {"type": "player_left", "player_id": "..."}
"""

import struct

import msgpack

MSG_JOIN = "join"
MSG_LEAVE = "leave"
MSG_INPUT = "input"
MSG_STATE_UPDATE = "state_update"
MSG_PLAYER_JOINED = "player_joined"
MSG_PLAYER_LEFT = "player_left"

_LENGTH_PREFIX = struct.Struct(">I")


def pack_message(message: dict) -> bytes:
    """Serialize a message dict to a length-prefixed msgpack frame."""
    payload = msgpack.packb(message, use_bin_type=True)
    return _LENGTH_PREFIX.pack(len(payload)) + payload


def recv_exactly(sock, num_bytes: int) -> bytes:
    """Read exactly `num_bytes` from `sock`, raising ConnectionError on EOF."""
    chunks = []
    remaining = num_bytes
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed while reading")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def recv_message(sock) -> dict:
    """Read one length-prefixed msgpack frame and return the decoded dict."""
    header = recv_exactly(sock, _LENGTH_PREFIX.size)
    (length,) = _LENGTH_PREFIX.unpack(header)
    payload = recv_exactly(sock, length)
    return msgpack.unpackb(payload, raw=False)


def derive_status(previous_status: str, direction_x: float, direction_y: float, attacking: bool) -> str:
    """Reduced port of the client's direction -> animation-status mapping.

    This duplicates the up/down/left/right + "_idle"/"_attack" core of
    `Player.input()` + `BasePlayer.get_status()` (Code/Player.py) for the
    cases RemotePlayer needs in v0 (no slide/sit/cooldown states). The
    server is the single source of truth for `status`, so this is the
    function that ships in `state_update`.

    Per the multiplayer plan's "Parallel-maintenance contract": this is one
    of the two documented v0 duplications. `tests/test_status_conformance.py`
    is the tripwire that checks it against `BasePlayer.get_status()` for the
    movement/idle cases v0 actually uses; Stage C (combat sync) is expected
    to be where `_attack` handling gets revisited.
    """
    status = previous_status

    # Base direction: mirrors Player.input()'s "vertical set first, then
    # horizontal overrides if also pressed" priority. An axis that's zero
    # this tick leaves the existing status alone, just like input() does.
    if direction_y < 0:
        status = "up"
    elif direction_y > 0:
        status = "down"
    if direction_x > 0:
        status = "right"
    elif direction_x < 0:
        status = "left"

    # Strip any inherited suffix before re-deriving it, mirroring
    # get_status()'s net effect for the idle/attack toggles.
    status = status.replace("_idle", "").replace("_attack", "")

    if direction_x == 0 and direction_y == 0:
        status += "_idle"
    elif attacking:
        status += "_attack"

    return status
