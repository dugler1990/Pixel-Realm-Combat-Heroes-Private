"""Inventory.has_room_for + Player.can_pickup (co-op shared-pickup pre-check).

The joiner must pre-check it can hold a shared item BEFORE asking the host to
award it (else the host removes it for both and it's lost). These are the
non-mutating room checks that gate that request. Stackable == effect_type
"consumable" (Inventory._item_is_stackable).
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

from Inventory import Inventory, MAX_STACK_PER_ITEM  # noqa: E402
from Player import BasePlayer  # noqa: E402


def _inv(slots):
    inv = Inventory.__new__(Inventory)
    inv.backpack_start_index = 0
    inv.belt_start_index = len(slots)
    inv.slots = slots
    return inv


def _slot(item=None, qty=0):
    return SimpleNamespace(item=item, quantity=qty)


def _item(item_id, effect_type="weapon"):
    return SimpleNamespace(item_id=item_id, effect_type=effect_type)


def test_has_room_when_an_empty_slot_exists():
    inv = _inv([_slot(_item("a"), 1), _slot(None)])
    assert inv.has_room_for(_item("b")) is True


def test_no_room_when_all_slots_full_non_stackable():
    inv = _inv([_slot(_item("a"), 1), _slot(_item("b"), 1)])
    assert inv.has_room_for(_item("c")) is False


def test_stackable_has_room_in_a_matching_unfilled_stack():
    inv = _inv([_slot(_item("potion", "consumable"), 1), _slot(_item("x"), 1)])
    assert inv.has_room_for(_item("potion", "consumable")) is True


def test_stackable_no_room_when_stack_maxed_and_slots_full():
    inv = _inv([_slot(_item("potion", "consumable"), MAX_STACK_PER_ITEM), _slot(_item("x"), 1)])
    assert inv.has_room_for(_item("potion", "consumable")) is False


def test_can_pickup_gold_is_always_true_even_when_full():
    player = SimpleNamespace(inventory=SimpleNamespace(has_room_for=lambda i: False))
    assert BasePlayer.can_pickup(player, _item("g", "gold")) is True


def test_can_pickup_nongold_defers_to_inventory_room():
    full = SimpleNamespace(inventory=SimpleNamespace(has_room_for=lambda i: False))
    room = SimpleNamespace(inventory=SimpleNamespace(has_room_for=lambda i: True))
    assert BasePlayer.can_pickup(full, _item("a")) is False
    assert BasePlayer.can_pickup(room, _item("a")) is True
