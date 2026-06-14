"""Tests for Level4's multiplayer inbox reconciliation (Milestone 3).

Drives the REAL Level4._process_multiplayer_inbox / _spawn_remote_player
methods against a lightweight duck-typed stub (so we don't pay the cost of
building a full headless Level4, which also can't run its draw loop here --
level 6's daytime path needs the GPU backend's draw_shadow). This covers the
join/leave/state_update reconciliation, and specifically the load-bearing
"lazy spawn on first state_update" path that lets a late-joining client learn
about players who joined before it connected.
"""

import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

from Level4_tmxdev import Level4  # noqa: E402
from PlayerSelection import unlocked_player_base_stats, unlocked_player_directory  # noqa: E402
from network import MSG_PLAYER_JOINED, MSG_PLAYER_LEFT, MSG_STATE_UPDATE  # noqa: E402

CHARACTER = unlocked_player_directory[0]
STATS = unlocked_player_base_stats[0]


class _FakeClient:
    """Stand-in for MultiplayerClient: poll() returns a queued batch per call."""

    def __init__(self, player_id):
        self.player_id = player_id
        self._batches = []

    def queue(self, *messages):
        self._batches.append(list(messages))

    def poll(self):
        return self._batches.pop(0) if self._batches else []


def _make_stub_level(my_id="me"):
    """Minimal object exposing exactly what the inbox methods read off self."""
    stub = SimpleNamespace(
        mp_client=_FakeClient(my_id),
        player_base_stats=dict(STATS),
        input_manager=SimpleNamespace(),
        layout_manager=SimpleNamespace(
            visible_sprites=pygame.sprite.Group(),
            obstacle_quad_tree=None,
            entity_quad_tree=None,
        ),
    )
    # Bind the real Level4 methods to the stub so self._spawn_remote_player etc.
    # resolve, without constructing a full (un-drawable) headless Level4.
    stub._spawn_remote_player = types.MethodType(Level4._spawn_remote_player, stub)
    stub._process_multiplayer_inbox = types.MethodType(Level4._process_multiplayer_inbox, stub)
    return stub


def _drain(stub):
    stub._process_multiplayer_inbox()


def _snap(pid, x, y, dx=0.0, dy=0.0, status="down_idle"):
    return {
        "character": CHARACTER, "x": x, "y": y,
        "direction_x": dx, "direction_y": dy, "status": status,
    }


def test_player_joined_spawns_remote_and_adds_to_visible_sprites():
    stub = _make_stub_level()
    stub.mp_client.queue({
        "type": MSG_PLAYER_JOINED, "player_id": "other",
        "character": CHARACTER, "x": 300.0, "y": 400.0,
    })
    _drain(stub)

    assert "other" in stub.remote_players
    remote = stub.remote_players["other"]
    assert remote in stub.layout_manager.visible_sprites.sprites()
    assert remote.rect.center == (300, 400)


def test_state_update_applies_snapshot_to_existing_remote():
    stub = _make_stub_level()
    stub.mp_client.queue({
        "type": MSG_PLAYER_JOINED, "player_id": "other",
        "character": CHARACTER, "x": 0.0, "y": 0.0,
    })
    _drain(stub)
    stub.mp_client.queue({
        "type": MSG_STATE_UPDATE, "tick": 1, "server_time_ms": 0.0,
        "players": {"other": _snap("other", 123.0, 456.0, 1.0, 0.0, "right")},
    })
    _drain(stub)

    remote = stub.remote_players["other"]
    remote.update()  # consume the stored snapshot
    assert remote.rect.center == (123, 456)
    assert remote.status == "right"


def test_state_update_lazy_spawns_unknown_player():
    # The late-joiner path: no player_joined was ever received for "early", yet
    # a state_update naming it must still produce a RemotePlayer.
    stub = _make_stub_level(my_id="me")
    stub.mp_client.queue({
        "type": MSG_STATE_UPDATE, "tick": 1, "server_time_ms": 0.0,
        "players": {
            "me": _snap("me", 10.0, 10.0),          # our own echo -- skipped
            "early": _snap("early", 700.0, 800.0),  # never announced via join
        },
    })
    _drain(stub)

    assert "me" not in stub.remote_players  # never puppet our own player
    assert "early" in stub.remote_players
    # Spawned at the snapshot's center coords, and the snapshot was applied.
    assert stub.remote_players["early"].rect.center == (700, 800)
    assert stub.remote_players["early"]._net_x == 700.0


def test_own_id_is_never_spawned_from_join_or_state():
    stub = _make_stub_level(my_id="me")
    stub.mp_client.queue(
        {"type": MSG_PLAYER_JOINED, "player_id": "me",
         "character": CHARACTER, "x": 0.0, "y": 0.0},
        {"type": MSG_STATE_UPDATE, "tick": 1, "server_time_ms": 0.0,
         "players": {"me": _snap("me", 50.0, 50.0)}},
    )
    _drain(stub)
    assert "me" not in getattr(stub, "remote_players", {})


def test_player_left_removes_and_kills_remote():
    stub = _make_stub_level()
    stub.mp_client.queue({
        "type": MSG_PLAYER_JOINED, "player_id": "other",
        "character": CHARACTER, "x": 0.0, "y": 0.0,
    })
    _drain(stub)
    remote = stub.remote_players["other"]

    stub.mp_client.queue({"type": MSG_PLAYER_LEFT, "player_id": "other"})
    _drain(stub)

    assert "other" not in stub.remote_players
    assert remote not in stub.layout_manager.visible_sprites.sprites()


def test_duplicate_join_does_not_double_spawn():
    stub = _make_stub_level()
    join = {
        "type": MSG_PLAYER_JOINED, "player_id": "other",
        "character": CHARACTER, "x": 0.0, "y": 0.0,
    }
    stub.mp_client.queue(join)
    _drain(stub)
    first = stub.remote_players["other"]
    stub.mp_client.queue(dict(join))
    _drain(stub)
    assert stub.remote_players["other"] is first
