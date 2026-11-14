"""What a hero wears: the body slots, which item fits which slot, what is drawn, the start gear.

Rules only, no pygame. Inventory.py holds the items and changes them; inventory_view.py draws the window and
moves the cursor; both ask this module what fits where.

Wearable items (an item's `effect_type`, `effect`):
    armour_equip   {"slot": kind, "side": "l" | "r" (optional), "mesh_piece": "<pack>/<piece>" (optional)}
    waist_equip    {"belt_slots": n, "mesh_piece": ... (optional)}: simple belt, loincloth, armour belt
    belt_equip     the old name of waist_equip (read the same; nothing writes it)
Sides are the hero's own: "l" is his left. The doll faces you, so his left is on screen right. Mesh pieces
are named the same way (`shoulder_l` is on his left arm: +X in model space, the rig faces -Y).
An item with no side fits either side.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

ARMOUR, WAIST, OLD_WAIST = "armour_equip", "waist_equip", "belt_equip"
ARMOUR_KINDS = ("helmet", "armor", "shoulder", "arm", "legs", "boots")


@dataclass(frozen=True)
class BodySlot:
    id: str
    kind: str
    side: str | None
    doll: tuple          # (x, y, w, h) as shares of the doll picture


# Order matters to old callers: helmet first, waist last (Inventory.waist_slot_index).
BODY = (
    BodySlot("helmet", "helmet", None, (0.37, 0.02, 0.26, 0.15)),
    BodySlot("armor", "armor", None, (0.35, 0.21, 0.30, 0.17)),
    BodySlot("shoulder_r", "shoulder", "r", (0.12, 0.19, 0.19, 0.08)),
    BodySlot("shoulder_l", "shoulder", "l", (0.69, 0.19, 0.19, 0.08)),
    BodySlot("arm_r", "arm", "r", (0.00, 0.47, 0.15, 0.09)),
    BodySlot("arm_l", "arm", "l", (0.85, 0.47, 0.15, 0.09)),
    BodySlot("weapon_r", "weapon", "r", (0.03, 0.58, 0.14, 0.19)),
    BodySlot("weapon_l", "weapon", "l", (0.83, 0.58, 0.14, 0.19)),
    BodySlot("legs_r", "legs", "r", (0.27, 0.62, 0.19, 0.14)),
    BodySlot("legs_l", "legs", "l", (0.54, 0.62, 0.19, 0.14)),
    BodySlot("boots_r", "boots", "r", (0.22, 0.90, 0.23, 0.09)),
    BodySlot("boots_l", "boots", "l", (0.58, 0.90, 0.23, 0.09)),
    BodySlot("waist", "waist", None, (0.35, 0.395, 0.30, 0.065)),
)

# Mesh piece (outfit pipeline slot pack name) -> (item type, body kind, side). equip_install.py makes the items.
PIECES = {
    "helmet": (ARMOUR, "helmet", None), "chest": (ARMOUR, "armor", None),
    "shoulder_l": (ARMOUR, "shoulder", "l"), "shoulder_r": (ARMOUR, "shoulder", "r"),
    "gauntlet_l": (ARMOUR, "arm", "l"), "gauntlet_r": (ARMOUR, "arm", "r"),
    "pants_l": (ARMOUR, "legs", "l"), "pants_r": (ARMOUR, "legs", "r"),
    "boot_l": (ARMOUR, "boots", "l"), "boot_r": (ARMOUR, "boots", "r"),
    "belt": (WAIST, "waist", None), "loincloth": (WAIST, "waist", None),
}
BELT_POCKETS = {"belt": 2, "loincloth": 1}     # a waist piece opens this many belt pockets (simple belt: 1)


def _effect(item):
    return (getattr(item, "effect", None) or {}) if item is not None else {}


def wearable(item):
    """(kind, side) of the body slot an item is worn in, else None."""
    kind = getattr(item, "effect_type", None) if item is not None else None
    if kind in (WAIST, OLD_WAIST):
        return "waist", None
    if kind == ARMOUR and _effect(item).get("slot") in ARMOUR_KINDS:
        return _effect(item)["slot"], _effect(item).get("side")
    return None


def fits_belt(item):
    return getattr(item, "belt_allowed", False) and getattr(item, "effect_type", None) == "consumable"


def fits(kind, side, item):
    """Can `item` go in a slot of this kind (and side)? kind: a body kind, "pack" or "belt".
    (A locked belt pocket is the inventory's to refuse: it depends on the waist.)"""
    if item is None:
        return False
    if kind == "pack":
        return True
    if kind == "belt":
        return fits_belt(item)
    worn = wearable(item)
    if kind == "weapon":
        return worn is None                      # weapons, and as before anything that is not worn
    if worn is None or worn[0] != kind:
        return False
    return worn[1] is None or side is None or worn[1] == side


def mesh_piece(item):
    """The mesh pack a worn item draws (Graphics/Meshes/<pack>/<piece>), else None."""
    return _effect(item).get("mesh_piece") if wearable(item) else None


def belt_pockets(waist_item):
    """How many belt pockets the item in the waist slot opens (0: none)."""
    if wearable(waist_item) != ("waist", None):
        return 0
    return max(0, int(_effect(waist_item).get("belt_slots", 1)))


def worn_pieces(items):
    """The mesh packs to draw for these worn items, in order, once each."""
    names = []
    for item in items:
        name = mesh_piece(item)
        if name and name not in names:
            names.append(name)
    return names


# --- start gear ----------------------------------------------------------------------------------------------

SELECTION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Graphics", "PlayerSelectionDict.json")
DEFAULT_START = {"wear": ["simple_belt"], "pack": []}


def start_equipment(mesh_pack=None, player_info_dir=None, path=SELECTION):
    """The hero's "start_equipment" ({"wear": [item ids], "pack": [item ids]}) from its PlayerSelectionDict.json
    entry: the one with this mesh_pack, or for a sprite hero the one with this player_info_dir and no mesh_pack.
    DEFAULT_START (the simple belt) when the entry has none."""
    try:
        with open(path, encoding="utf-8") as fh:
            players = json.load(fh).get("Players", [])
    except (OSError, ValueError):
        return DEFAULT_START
    norm = (player_info_dir or "").rstrip("/")
    for entry in players:
        if mesh_pack:
            match = entry.get("mesh_pack") == mesh_pack
        else:
            match = not entry.get("mesh_pack") and entry.get("player_info_dir", "").rstrip("/") == norm
        if match:
            return entry.get("start_equipment") or DEFAULT_START
    return DEFAULT_START


def give_start_equipment(inventory, start, make_item):
    """Put the start gear on / in the pack. make_item(item_id) -> item or None (unknown id: skipped).
    Returns the ids it could not make."""
    unknown = []
    for key in ("wear", "pack"):
        for item_id in start.get(key, []):
            item = make_item(item_id)
            if item is None:
                unknown.append(item_id)
            elif not (key == "wear" and inventory.wear(item)):
                inventory.add_item(item)
    return unknown
