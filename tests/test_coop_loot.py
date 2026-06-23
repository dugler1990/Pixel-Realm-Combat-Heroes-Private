"""Co-op (Stage C / CS5) Level4 reward/loot CLIENT handlers, driven via stubs.

Exercises the REAL Level4 client-side handlers (`_handle_enemy_died`,
`_handle_item_dropped`, `_handle_item_removed`) against duck-typed stubs + mocks
-- no full headless Level4. Confirms death FX + XP fire, shared loot is tracked
by drop_id, and a server-arbitrated removal awards the item only to the `to`
player (no double-grant). The server-side roll + pickup arbitration live in
tests/test_server_enemy_authority.py.
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


def test_handle_enemy_died_plays_fx_awards_xp_and_removes_puppet():
    puppet = SimpleNamespace(death_sound=SimpleNamespace(play=Mock()), kill=Mock())
    stub = SimpleNamespace(
        trigger_death_particles=Mock(),
        add_exp=Mock(),
        enemy_puppets={7: puppet},
    )
    Level4._handle_enemy_died(stub, {"id": 7, "x": 10, "y": 20, "monster": "squid", "exp": 5})
    stub.trigger_death_particles.assert_called_once_with((10, 20), "squid")
    stub.add_exp.assert_called_once_with(5)              # joiner gains the same XP
    puppet.kill.assert_called_once()
    assert 7 not in stub.enemy_puppets


def test_handle_item_dropped_tracks_shared_visual_by_drop_id():
    fake_item = SimpleNamespace(item_id="gold_coin", pos=[10, 20])
    fake_visual = SimpleNamespace()
    stub = SimpleNamespace(
        item_spawner=SimpleNamespace(item_mapping={"gold_coin": {"image_path": "x"}},
                                     create_item=lambda cfg, pos: fake_item),
        layout_manager=SimpleNamespace(add_item_visual=lambda item: fake_visual),
        _shared_items={},
    )
    Level4._handle_item_dropped(stub, {"drop_id": 31, "item_id": "gold_coin", "x": 10, "y": 20})
    assert fake_visual._drop_id == 31
    assert stub._shared_items[31] is fake_visual


def _removal_stub(my_id="me"):
    return SimpleNamespace(
        mp_client=SimpleNamespace(player_id=my_id, send_item_removed=Mock()),
        _requested_pickups=set(),
        player=SimpleNamespace(pickup_item=Mock()),
        item_spawner=SimpleNamespace(remove_item=Mock()),
    )


def test_item_removed_grants_only_to_the_awarded_player():
    fake_item = SimpleNamespace()
    visual = SimpleNamespace(item=fake_item, kill=Mock())
    stub = _removal_stub(my_id="me")
    stub._shared_items = {31: visual}
    stub._requested_pickups = {31}
    Level4._handle_item_removed(stub, 31, to="me")
    stub.player.pickup_item.assert_called_once_with(fake_item)
    visual.kill.assert_called_once()
    assert 31 not in stub._shared_items and 31 not in stub._requested_pickups


def test_item_removed_does_not_double_grant_when_awarded_to_someone_else():
    # The dupe guard: I requested it, but the host awarded it to another player
    # (e.g. the host grabbed it first). I must clear the visual but NOT bank it.
    visual = SimpleNamespace(item=SimpleNamespace(), kill=Mock())
    stub = _removal_stub(my_id="me")
    stub._shared_items = {31: visual}
    stub._requested_pickups = {31}
    Level4._handle_item_removed(stub, 31, to="someone_else")
    stub.player.pickup_item.assert_not_called()
    visual.kill.assert_called_once()
    assert 31 not in stub._requested_pickups


def test_item_removed_despawn_to_none_clears_visual_only():
    visual = SimpleNamespace(item=SimpleNamespace(), kill=Mock())
    stub = _removal_stub(my_id="me")
    stub._shared_items = {31: visual}
    Level4._handle_item_removed(stub, 31, to=None)
    stub.player.pickup_item.assert_not_called()
    visual.kill.assert_called_once()


# (CS5b: pickup arbitration moved off the client to the SERVER --
#  ServerLevel.arbitrate_pickup, covered in tests/test_server_enemy_authority.py.)
