"""Wearable pieces: inventory rules (Code/Inventory.py), what a mesh player wears (Player.refresh_equipment ->
PlayerMesh.set_pieces), how a piece is drawn (PlayerMesh.draw: the body's pivot, scale and frame, one depth clear),
and the generated items (Graphics/Standard_Items/outfit_items.json). No GPU: a backend that records its calls."""
import json
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

import pytest  # noqa: E402

from Inventory import BODY_SLOTS, Inventory  # noqa: E402

ITEMS = REPO_ROOT / "Graphics" / "Standard_Items" / "outfit_items.json"


def piece(slot, name, belt=None):
    effect = {"slot": slot, "mesh_piece": f"barb_fullplate/{name}"}
    if belt:
        effect["belt_slots"] = belt
    return SimpleNamespace(item_id=f"barb_fullplate_{name}", effect_type="armour_equip", effect=effect,
                           image_path=None)


class FakePlayer:
    has_belt, belt_capacity = False, 0

    def __init__(self):
        self.worn = None

    def refresh_equipment(self):
        self.worn = self.inventory.worn_pieces()


def make_inventory():
    player = FakePlayer()
    inv = Inventory(player, SimpleNamespace())
    player.inventory = inv
    return inv, player


def body_slot(inv, kind, n=0):
    return [s for s in inv.slots[:len(BODY_SLOTS)] if s.slot_type == kind][n]


def test_armour_goes_only_in_its_slot():
    inv, _ = make_inventory()
    chest, boot = piece("armor", "chest"), piece("boots", "boot_l")
    potion = SimpleNamespace(item_id="potion", effect_type="consumable", effect={}, belt_allowed=True)
    assert inv._can_place_in_slot(body_slot(inv, "armor"), chest)
    assert not inv._can_place_in_slot(body_slot(inv, "armor"), boot)
    assert not inv._can_place_in_slot(body_slot(inv, "armor"), potion)
    assert inv._can_place_in_slot(body_slot(inv, "boots", 1), boot)
    assert not inv._can_place_in_slot(body_slot(inv, "weapon"), chest)
    assert inv._can_place_in_slot(inv.slots[inv.backpack_start_index], chest)     # the backpack holds anything


def test_waist_takes_a_belt_the_loincloth_or_the_armour_belt():
    inv, player = make_inventory()
    waist = inv.slots[inv.waist_slot_index]
    assert waist.slot_type == "waist"
    loincloth = SimpleNamespace(item_id="barb_loincloth_loincloth", effect_type="armour_equip",
                                effect={"slot": "waist", "mesh_piece": "barb_loincloth/loincloth", "belt_slots": 1})
    belt = SimpleNamespace(item_id="simple_belt", effect_type="belt_equip", effect={"belt_slots": 1})
    for item in (loincloth, belt, piece("waist", "belt", belt=2)):
        assert inv._can_place_in_slot(waist, item)
    assert not inv._can_place_in_slot(waist, piece("armor", "chest"))
    assert inv.wear(loincloth)
    assert player.has_belt and player.belt_capacity == 1                        # the loincloth opens a pocket
    assert player.worn == ["barb_loincloth/loincloth"]


def test_putting_on_and_taking_off_changes_what_is_worn():
    inv, player = make_inventory()
    chest, shoulder = piece("armor", "chest"), piece("shoulder", "shoulder_l")
    inv.add_item(chest)
    inv.add_item(shoulder)
    src = inv.slots[inv.backpack_start_index]
    inv._lift_from_slot(src)
    inv._place_or_swap(body_slot(inv, "armor"))
    assert player.worn == ["barb_fullplate/chest"]
    assert inv.wear(shoulder) and player.worn == ["barb_fullplate/chest", "barb_fullplate/shoulder_l"]
    inv._lift_from_slot(body_slot(inv, "armor"))
    assert player.worn == ["barb_fullplate/shoulder_l"]


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def draw_mesh_boss(self, pack, frame, pos, yaw, scale, elev, light, amb, **kw):
        self.calls.append((pack.name, frame, scale, kw))
        return True


def test_a_piece_is_drawn_about_the_body_pivot_on_the_body_frame():
    if not (REPO_ROOT / "Graphics" / "Meshes" / "barb_fullplate" / "chest" / "skin.npz").is_file():
        pytest.skip("barb_fullplate not installed (tools/boss_sprite_pipeline/equip_install.py)")
    from player_mesh import PlayerMesh
    m = PlayerMesh("barb", 120)
    m.set_pieces(["barb_fullplate/chest", "barb_fullplate/missing"])            # a missing pack is left out
    assert list(m.pieces) == ["barb_fullplate/chest"]
    m.skin.set_action("move")
    m.skin.frame = 5.0
    b = RecordingBackend()
    assert m.draw(b, (100, 200))
    (body, f0, s0, kw0), (chest, f1, s1, kw1) = b.calls
    assert body == "barb" and chest == "barb_fullplate/chest"
    assert f1 == m.pieces["barb_fullplate/chest"].pack.ranges["move"][0] + 5 and s1 == s0
    assert kw0.get("clear_pad", 0) > 0 and kw1["clear_depth"] is False
    assert list(kw1["pivot"]) == list(m.skin.pack.pivot)


def test_generated_items_point_at_installed_packs_and_icons():
    if not ITEMS.is_file():
        pytest.skip("no outfit_items.json")
    for e in json.loads(ITEMS.read_text(encoding="utf-8")):
        assert e["effect_type"] == "armour_equip" and e["effect"]["slot"] in BODY_SLOTS, e["item_id"]
        assert (REPO_ROOT / "Graphics" / "Meshes" / e["effect"]["mesh_piece"] / "skin.npz").is_file(), e["item_id"]
        assert (CODE_DIR / e["image_path"]).resolve().is_file(), e["image_path"]
