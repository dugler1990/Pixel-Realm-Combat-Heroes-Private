"""The inventory window's one cursor (Code/inventory_view.py): the arrows move to the nearest slot in that
direction over the doll, the pack and the belt, laid out as the game lays them out (CPU backend)."""
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
os.chdir(CODE_DIR)                       # the kit loads its pictures from ../Graphics

import pygame  # noqa: E402
import pytest  # noqa: E402

pygame.init()

import legion_ui as L  # noqa: E402
from Inventory import Inventory  # noqa: E402
from render_backend import CPUBackend  # noqa: E402

UP, DOWN, LEFT, RIGHT = (0, -1), (0, 1), (-1, 0), (1, 0)

# from: {direction: to}. The doll faces you: his right (_r) on screen left. "-": an edge, the cursor stays.
EXPECTED = {
    "helmet": {UP: "-", DOWN: "armor", LEFT: "shoulder_r", RIGHT: "shoulder_l"},
    "armor": {UP: "helmet", DOWN: "waist", LEFT: "shoulder_r", RIGHT: "shoulder_l"},
    "shoulder_r": {UP: "helmet", DOWN: "arm_r", LEFT: "-", RIGHT: "armor"},
    "shoulder_l": {UP: "helmet", DOWN: "arm_l", LEFT: "armor", RIGHT: "pack_0"},
    "arm_r": {UP: "shoulder_r", DOWN: "weapon_r", LEFT: "-"},
    "arm_l": {UP: "shoulder_l", DOWN: "weapon_l", RIGHT: "pack_3"},
    "waist": {UP: "armor", LEFT: "arm_r", RIGHT: "arm_l"},
    "weapon_r": {UP: "arm_r", DOWN: "boots_r", RIGHT: "legs_r"},
    "weapon_l": {UP: "arm_l", DOWN: "boots_l", LEFT: "legs_l", RIGHT: "pack_6"},
    "legs_r": {UP: "waist", DOWN: "boots_r", LEFT: "weapon_r", RIGHT: "legs_l"},
    "legs_l": {UP: "waist", DOWN: "boots_l", LEFT: "legs_r", RIGHT: "weapon_l"},
    "boots_r": {UP: "legs_r", RIGHT: "boots_l"},
    "boots_l": {UP: "legs_l", LEFT: "boots_r", RIGHT: "pack_9"},
    "pack_0": {UP: "-", DOWN: "pack_3", LEFT: "shoulder_l", RIGHT: "pack_1"},
    "pack_3": {LEFT: "arm_l"},
    "pack_6": {LEFT: "weapon_l"},
    "pack_9": {UP: "pack_6", DOWN: "-", LEFT: "boots_l", RIGHT: "pack_10"},
    "pack_2": {RIGHT: "-"},
    "belt_0": {UP: "boots_r", LEFT: "-", RIGHT: "belt_1"},
}


def window(size, pockets):
    screen = pygame.display.set_mode(size)
    player = SimpleNamespace(has_belt=pockets > 0, belt_capacity=pockets)
    inv = Inventory(player, SimpleNamespace())
    inv.view.layout(L.kit_for(CPUBackend(screen)))
    return inv


def go(inv, start, direction):
    inv.view.cursor = inv.slots.index(inv.slot(start))
    inv.view.move(*direction)
    return inv.slots[inv.view.cursor].id


@pytest.mark.parametrize("size", [(800, 600), (1280, 720), (1920, 1080)])
def test_arrows_go_where_the_slots_are(size):
    inv = window(size, pockets=2)
    for start, moves in EXPECTED.items():
        for direction, want in moves.items():
            got = go(inv, start, direction)
            assert got == (start if want == "-" else want), (size, start, direction, got)


@pytest.mark.parametrize("pockets", [0, 1, 4])
def test_every_open_slot_is_reachable_and_closed_pockets_are_not(pockets):
    inv = window((1280, 720), pockets)
    open_ids = {s.id for i, s in enumerate(inv.slots) if inv.view.reachable(i)}
    seen, todo = set(), ["pack_0"]
    while todo:
        sid = todo.pop()
        if sid in seen:
            continue
        seen.add(sid)
        todo += [go(inv, sid, d) for d in (UP, DOWN, LEFT, RIGHT)]
    assert seen == open_ids
    assert {f"belt_{i}" for i in range(pockets)} <= seen and not {f"belt_{i}" for i in range(pockets, 4)} & seen


def test_tab_jumps_area_and_skips_a_closed_belt():
    inv = window((1280, 720), pockets=0)
    inv.view.cursor = inv.backpack_start_index
    inv.view.next_area()
    assert inv.area(inv.view.cursor) == "body"                # pack -> (no belt) -> body
    inv.view.next_area()
    assert inv.area(inv.view.cursor) == "pack"
