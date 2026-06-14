"""Conformance check for the multiplayer "Parallel-maintenance contract".

`Code/network/protocol.derive_status` is a reduced, server-side port of
`Player.input()` + `BasePlayer.get_status()`'s direction -> animation-status
mapping (Code/Player.py). This test is the tripwire: if `get_status()`'s
core up/down/left/right/_idle behavior changes, this should fail so the
divergence gets noticed and `derive_status` gets updated to match.

`_attack` transitions are out of scope here -- v0 multiplayer is
movement-sync only (see the multiplayer plan's "Parallel-maintenance
contract" / Stage C).
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()

from network.protocol import derive_status  # noqa: E402
from Player import BasePlayer  # noqa: E402


class _DummyDirection:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _DummyPlayer:
    def __init__(self, status, direction_x, direction_y, attacking):
        self.status = status
        self.direction = _DummyDirection(direction_x, direction_y)
        self.attacking = attacking


def _client_reference_status(previous_status, direction_x, direction_y, attacking):
    """One frame of Player.input() + BasePlayer.get_status(), movement only.

    input() sets the base direction string (vertical first, then horizontal
    overrides) only for axes that are non-zero this frame, leaving the
    existing status alone otherwise; get_status() then adds/removes the
    "_idle"/"_attack" suffix.
    """
    status = previous_status
    if direction_y < 0:
        status = "up"
    elif direction_y > 0:
        status = "down"
    if direction_x > 0:
        status = "right"
    elif direction_x < 0:
        status = "left"

    player = _DummyPlayer(status, direction_x, direction_y, attacking)
    BasePlayer.get_status(player)
    return player.status


# (previous_status, direction_x, direction_y, attacking)
MOVEMENT_CASES = [
    ("down_idle", 0, -1, False),  # idle -> up
    ("down_idle", 0, 1, False),  # idle -> down
    ("down_idle", -1, 0, False),  # idle -> left
    ("down_idle", 1, 0, False),  # idle -> right
    ("up", 0, 0, False),  # moving -> idle
    ("down", 0, 0, False),
    ("left", 0, 0, False),
    ("right", 0, 0, False),
    ("up_idle", 0, 0, False),  # already idle, stays idle
    ("right", -1, 0, False),  # direct left/right switch
    ("left_idle", 0, -1, False),  # idle -> up while previously idle
    ("up", 1, -1, False),  # diagonal: horizontal wins over vertical
]


@pytest.mark.parametrize("previous_status, direction_x, direction_y, attacking", MOVEMENT_CASES)
def test_server_status_matches_client(previous_status, direction_x, direction_y, attacking):
    expected = _client_reference_status(previous_status, direction_x, direction_y, attacking)
    actual = derive_status(previous_status, direction_x, direction_y, attacking)
    assert actual == expected
