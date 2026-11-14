"""Wearable pieces: the rules (Code/equipment.py), the inventory changes that use them (Code/Inventory.py), what a
mesh player draws (PlayerMesh.draw: the body's pivot, scale and frame, one depth clear), the generated items
(Graphics/Standard_Items/outfit_items.json) and the start gear (PlayerSelectionDict.json). No GPU: a backend that
records its calls."""
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

import equipment  # noqa: E402
from Inventory import Inventory  # noqa: E402

ITEMS = REPO_ROOT / "Graphics" / "Standard_Items" / "outfit_items.json"


def piece(kind, name, side=None):
    effect = {"slot": kind, "mesh_piece": f"barb_fullplate/{name}", **({"side": side} if side else {})}
    return SimpleNamespace(item_id=f"barb_fullplate_{name}", effect_type="armour_equip", effect=effect,
                           image_path=None)


def waist(item_id, pockets, mesh=None, effect_type="waist_equip"):
    effect = {"belt_slots": pockets, **({"mesh_piece": mesh} if mesh else {})}
    return SimpleNamespace(item_id=item_id, effect_type=effect_type, effect=effect, image_path=None)


POTION = SimpleNamespace(item_id="potion", effect_type="consumable", effect={}, belt_allowed=True, image_path=None)


# --- the rules ---------------------------------------------------------------------------------------------

def test_armour_fits_its_kind_and_side():
    chest, boot_l = piece("armor", "chest"), piece("boots", "boot_l", "l")
    assert equipment.fits("armor", None, chest)
    assert not equipment.fits("armor", None, boot_l)
    assert equipment.fits("boots", "l", boot_l)
    assert not equipment.fits("boots", "r", boot_l)                  # his left boot, not on his right foot
    assert equipment.fits("boots", "r", piece("boots", "old_boot"))  # an item with no side fits either
    assert not equipment.fits("armor", None, POTION)
    assert not equipment.fits("weapon", "r", chest) and equipment.fits("weapon", "r", POTION)
    assert equipment.fits("pack", None, chest)
    assert equipment.fits("belt", None, POTION) and not equipment.fits("belt", None, chest)


def test_waist_items_are_one_kind_and_open_pockets():
    simple, old = waist("simple_belt", 1), waist("simple_belt", 1, effect_type="belt_equip")
    loincloth = waist("barb_loincloth_loincloth", 1, "barb_loincloth/loincloth")
    for item in (simple, old, loincloth):
        assert equipment.wearable(item) == ("waist", None) and equipment.fits("waist", None, item)
    assert not equipment.fits("waist", None, piece("armor", "chest"))
    assert equipment.belt_pockets(waist("armour_belt", 2)) == 2 and equipment.belt_pockets(None) == 0
    assert equipment.worn_pieces([simple, loincloth, piece("armor", "chest")]) == [
        "barb_loincloth/loincloth", "barb_fullplate/chest"]


def test_every_piece_has_a_body_slot():
    kinds = {(b.kind, b.side) for b in equipment.BODY}
    for name, (item_type, kind, side) in equipment.PIECES.items():
        assert (kind, side) in kinds, name


def test_start_equipment_from_the_selection_entry(tmp_path):
    path = tmp_path / "sel.json"
    path.write_text(json.dumps({"Players": [
        {"player_info_dir": "../Graphics/barb/"},
        {"player_info_dir": "../Graphics/barb/", "mesh_pack": "barb", "start_equipment": {"wear": ["x"], "pack": []}},
    ]}), encoding="utf-8")
    assert equipment.start_equipment("barb", "../Graphics/barb/", path)["wear"] == ["x"]
    assert equipment.start_equipment(None, "../Graphics/barb", path) == equipment.DEFAULT_START
    assert equipment.start_equipment("other", None, path) == equipment.DEFAULT_START


# --- the inventory ----------------------------------------------------------------------------------------

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


def test_body_slots_have_ids_and_sides():
    inv, _ = make_inventory()
    assert inv.slot("shoulder_l").kind == "shoulder" and inv.slot("shoulder_l").side == "l"
    assert inv.slots[inv.waist_slot_index].id == "waist"
    assert inv.area(inv.backpack_start_index) == "pack" and inv.area(inv.belt_start_index) == "belt"


def test_lift_and_place_put_on_and_take_off():
    inv, player = make_inventory()
    chest = piece("armor", "chest")
    inv.add_item(chest)
    src = inv.pack_slots()[0]
    assert inv.lift(src)
    assert not inv.place(inv.slot("helmet"))                         # refused: the chest stays in hand
    assert inv.place(inv.slot("armor")) and player.worn == ["barb_fullplate/chest"]
    assert inv.lift(inv.slot("armor")) and player.worn == []


def test_put_on_from_the_pack_goes_to_its_side_and_swaps():
    inv, player = make_inventory()
    left, right = piece("shoulder", "shoulder_l", "l"), piece("shoulder", "shoulder_r", "r")
    inv.add_item(right)
    inv.add_item(left)
    assert inv.put_on(inv.pack_slots()[1])
    assert inv.slot("shoulder_l").item is left and inv.pack_slots()[1].empty
    assert inv.put_on(inv.pack_slots()[0]) and inv.slot("shoulder_r").item is right
    other = piece("shoulder", "shoulder_l_v2", "l")
    inv.add_item(other)
    assert inv.put_on(inv.pack_slots()[0])                            # a full slot: the worn one comes off
    assert inv.slot("shoulder_l").item is other and inv.pack_slots()[0].item is left
    assert player.worn == ["barb_fullplate/shoulder_r", "barb_fullplate/shoulder_l_v2"]


def test_waist_opens_pockets_and_closing_ones_empties_them():
    inv, player = make_inventory()
    assert inv.wear(waist("armour_belt", 2, "barb_fullplate/belt"))
    assert player.has_belt and player.belt_capacity == 2
    pocket = inv.belt_slots()[1]
    pocket.item, pocket.quantity = POTION, 3
    inv.hand_item, inv.hand_qty = waist("barb_loincloth_loincloth", 1, "barb_loincloth/loincloth"), 1
    assert inv.place(inv.slots[inv.waist_slot_index])                 # swap: the armour belt into the hand
    assert player.belt_capacity == 1 and pocket.empty
    assert inv.pack_slots()[0].item is POTION and inv.pack_slots()[0].quantity == 3
    assert player.worn == ["barb_loincloth/loincloth"]
    assert not inv.can_place(inv.belt_slots()[1], POTION) and inv.can_place(inv.belt_slots()[0], POTION)


def test_start_gear_wears_and_packs():
    inv, player = make_inventory()
    made = {"loin": waist("loin", 1, "barb_loincloth/loincloth"), "chest": piece("armor", "chest")}
    unknown = equipment.give_start_equipment(inv, {"wear": ["loin"], "pack": ["chest", "nope"]}, made.get)
    assert unknown == ["nope"]
    assert inv.slots[inv.waist_slot_index].item is made["loin"] and inv.pack_slots()[0].item is made["chest"]
    assert player.belt_capacity == 1 and player.worn == ["barb_loincloth/loincloth"]


# --- the draw, the generated items, the selection file ----------------------------------------------------

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
    assert PlayerMesh("barb", 120).pieces == {}                                 # not shared between players
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
    kinds = {(b.kind, b.side) for b in equipment.BODY}
    for e in json.loads(ITEMS.read_text(encoding="utf-8")):
        item = SimpleNamespace(**e)
        assert equipment.wearable(item) in kinds, e["item_id"]
        assert (REPO_ROOT / "Graphics" / "Meshes" / e["effect"]["mesh_piece"] / "skin.npz").is_file(), e["item_id"]
        assert (CODE_DIR / e["image_path"]).resolve().is_file(), e["image_path"]


def test_start_equipment_in_the_selection_file_names_known_items():
    names = {e["item_id"] for e in json.loads(ITEMS.read_text(encoding="utf-8"))} if ITEMS.is_file() else set()
    standard = REPO_ROOT / "Graphics" / "Standard_Items" / "standard_items.json"
    names |= {e["item_id"] for e in json.loads(standard.read_text(encoding="utf-8"))}
    sel = json.loads((REPO_ROOT / "Graphics" / "PlayerSelectionDict.json").read_text(encoding="utf-8"))
    for entry in sel["Players"]:
        start = entry.get("start_equipment") or {}
        for item_id in start.get("wear", []) + start.get("pack", []):
            assert item_id in names, (entry["name"], item_id)
