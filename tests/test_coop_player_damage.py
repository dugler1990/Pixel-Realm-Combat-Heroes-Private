"""CS4 client side: applying a server-relayed enemy->player hit.

When a server-owned enemy hits a player, the server broadcasts a `hit_player`
event; each client applies it to its OWN real player only (filtering by
target_player_id) via the existing get_damage (its own i-frames/death). Covers
the inbox routing + the apply, driven against duck-typed stubs.
"""

import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

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
from network import MSG_ENEMY_DIED, MSG_HIT_PLAYER  # noqa: E402


class _FakeClient:
    def __init__(self, pid):
        self.player_id = pid
        self._batches = []

    def queue(self, *messages):
        self._batches.append(list(messages))

    def poll(self):
        return self._batches.pop(0) if self._batches else []


def test_apply_relayed_player_hit_damages_local_player():
    stub = SimpleNamespace(player=SimpleNamespace(get_damage=Mock()))
    Level4._apply_relayed_player_hit(stub, 8, "melee")
    stub.player.get_damage.assert_called_once_with(8, "melee")


def test_apply_relayed_player_hit_ignores_none_amount():
    stub = SimpleNamespace(player=SimpleNamespace(get_damage=Mock()))
    Level4._apply_relayed_player_hit(stub, None, "melee")
    stub.player.get_damage.assert_not_called()


def test_inbox_applies_hit_player_only_to_my_id():
    stub = SimpleNamespace(mp_client=_FakeClient("me"))
    stub._process_multiplayer_inbox = types.MethodType(Level4._process_multiplayer_inbox, stub)
    stub._apply_relayed_player_hit = Mock()
    stub.mp_client.queue(
        {"type": MSG_HIT_PLAYER, "target_player_id": "me", "amount": 8, "attack_type": "melee"},
        {"type": MSG_HIT_PLAYER, "target_player_id": "other", "amount": 99, "attack_type": "melee"},
    )
    stub._process_multiplayer_inbox()
    stub._apply_relayed_player_hit.assert_called_once_with(8, "melee")  # not the "other" hit


def test_inbox_routes_enemy_died_for_any_role():
    # CS5a: server-authoritative -> EVERY client handles enemy_died (no longer
    # gated on the joiner role). Drive the inbox with a non-joiner role set.
    stub = SimpleNamespace(mp_client=_FakeClient("me"), _mp_role="host")
    stub._process_multiplayer_inbox = types.MethodType(Level4._process_multiplayer_inbox, stub)
    stub._handle_enemy_died = Mock()
    stub.mp_client.queue({"type": MSG_ENEMY_DIED, "id": 7, "x": 1, "y": 2,
                          "monster": "squid", "exp": 5})
    stub._process_multiplayer_inbox()
    stub._handle_enemy_died.assert_called_once()
