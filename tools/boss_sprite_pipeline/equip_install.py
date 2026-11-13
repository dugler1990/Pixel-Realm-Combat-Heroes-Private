"""Put an outfit's slot packs in the game as wearable items (after export_outfit.py).

    python -m tools.boss_sprite_pipeline.equip_install <character> <outfit>

For an armour or cut outfit whose export made <run>/packs/<slot>/:
- each pack copied to Graphics/Meshes/<pack>/<slot>/ (the game loads it as "<pack>/<slot>");
- an icon per slot (explode2/piece_icons.py) -> Graphics/Standard_Items/outfits/<pack>_<slot>.png;
- one item per slot in Graphics/Standard_Items/outfit_items.json (this outfit's entries replaced, others kept):
  item_id <pack>_<slot>, effect_type "armour_equip", effect {"slot": <inventory body slot>, "mesh_piece":
  "<pack>/<slot>"} (+ "belt_slots" for the waist).
A hero gets them from its body pack's equipment.json ({"wear": [...], "pack": [...]}, Level4 seeds it).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from tools.boss_sprite_pipeline import outfit as of

REPO = of.REPO
ITEMS = REPO / "Graphics" / "Standard_Items" / "outfit_items.json"
ICONS = REPO / "Graphics" / "Standard_Items" / "outfits"
# Slot pack -> the inventory's body slot (Code/Inventory.py BODY_SLOTS).
BODY_SLOT = {"chest": "armor", "belt": "waist", "loincloth": "waist", "helmet": "helmet",
             "shoulder_l": "shoulder", "shoulder_r": "shoulder", "gauntlet_l": "arm", "gauntlet_r": "arm",
             "pants_l": "legs", "pants_r": "legs", "boot_l": "boots", "boot_r": "boots"}
BELT_SLOTS = {"belt": 2, "loincloth": 1}       # a waist piece opens this many belt pockets (simple_belt: 1)


def install(character: str, outfit: str) -> dict:
    ctx = of.Ctx(character, outfit)
    pack = ctx.o["pack"]
    packs = ctx.work / "packs"
    info = json.loads((packs / "slot_packs.json").read_text(encoding="utf-8"))
    slots = [s for s in sorted(info) if (packs / s / "skin.npz").is_file()]
    missing = sorted(set(slots) - set(BODY_SLOT))
    if missing:
        sys.exit(f"no inventory slot for {missing}: add them to BODY_SLOT")
    dst_root = REPO / "Graphics" / "Meshes" / pack
    for s in slots:
        dst = dst_root / s
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(packs / s, dst)
    of.call([ctx.bpy, of.TOOLS / "explode2" / "piece_icons.py", packs, ICONS / "_tmp", *slots], ok="ICONS_OK",
            show=False)
    entries = []
    for s in slots:
        icon = ICONS / f"{pack}_{s}.png"
        shutil.move(str(ICONS / "_tmp" / f"{s}.png"), icon)
        effect = {"slot": BODY_SLOT[s], "mesh_piece": f"{pack}/{s}"}
        if s in BELT_SLOTS:
            effect["belt_slots"] = BELT_SLOTS[s]
        entries.append({"item_id": f"{pack}_{s}", "item_type": "armour", "spawn_type": "droppable", "positions": [],
                        "image_path": f"../Graphics/Standard_Items/outfits/{pack}_{s}.png", "effect": effect,
                        "effect_type": "armour_equip", "outfit": f"{character}/{outfit}"})
    shutil.rmtree(ICONS / "_tmp", ignore_errors=True)
    old = json.loads(ITEMS.read_text(encoding="utf-8")) if ITEMS.is_file() else []
    keep = [e for e in old if e.get("outfit") != f"{character}/{outfit}"]
    ITEMS.write_text(json.dumps(keep + entries, indent=1), encoding="utf-8")
    print(f"  {len(entries)} items: {', '.join(e['item_id'] for e in entries)}")
    return {"items": [e["item_id"] for e in entries], "meshes": str(dst_root)}


def main(argv=None) -> None:
    character, outfit = (argv or sys.argv[1:])[:2]
    print("EQUIP_INSTALL_OK", json.dumps(install(character, outfit)))


if __name__ == "__main__":
    main()
