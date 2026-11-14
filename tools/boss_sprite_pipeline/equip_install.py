"""Put an outfit's slot packs in the game as wearable items (after export_outfit.py).

    python -m tools.boss_sprite_pipeline.equip_install <character> <outfit> [--items-only]

For an armour or cut outfit whose export made <run>/packs/<slot>/:
- each pack copied to Graphics/Meshes/<pack>/<slot>/ (the game loads it as "<pack>/<slot>");
- an icon per slot (explode2/piece_icons.py) -> Graphics/Standard_Items/outfits/<pack>_<slot>.png;
- one item per slot in Graphics/Standard_Items/outfit_items.json (this outfit's entries replaced, others kept),
  item_id <pack>_<slot>, from Code/equipment.py PIECES: armour "armour_equip" {"slot", "side", "mesh_piece"},
  waist pieces "waist_equip" {"belt_slots", "mesh_piece"}.
--items-only: only the items, from the packs already in Graphics/Meshes/<pack>/ (no run folder, no Blender).
A hero gets them from its PlayerSelectionDict.json entry's "start_equipment" (equipment.start_equipment).
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
sys.path.insert(0, str(REPO / "Code"))
import equipment  # noqa: E402  (the game's table: piece -> item type, body slot, side, belt pockets)


def item(character: str, outfit: str, pack: str, piece: str) -> dict:
    kind_type, kind, side = equipment.PIECES[piece]
    effect = {"mesh_piece": f"{pack}/{piece}"}
    if kind_type == equipment.WAIST:
        effect["belt_slots"] = equipment.BELT_POCKETS.get(piece, 1)
    else:
        effect.update({"slot": kind, **({"side": side} if side else {})})
    return {"item_id": f"{pack}_{piece}", "item_type": "armour", "spawn_type": "droppable", "positions": [],
            "image_path": f"../Graphics/Standard_Items/outfits/{pack}_{piece}.png", "effect": effect,
            "effect_type": kind_type, "outfit": f"{character}/{outfit}"}


def install(character: str, outfit: str, items_only: bool = False) -> dict:
    ctx = of.Ctx(character, outfit)
    pack = ctx.o["pack"]
    dst_root = REPO / "Graphics" / "Meshes" / pack
    if items_only:
        slots = sorted(p.name for p in dst_root.iterdir() if (p / "skin.npz").is_file())
    else:
        packs = ctx.work / "packs"
        info = json.loads((packs / "slot_packs.json").read_text(encoding="utf-8"))
        slots = [s for s in sorted(info) if (packs / s / "skin.npz").is_file()]
    missing = sorted(set(slots) - set(equipment.PIECES))
    if missing:
        sys.exit(f"no body slot for {missing}: add them to Code/equipment.py PIECES")
    if not items_only:
        for s in slots:
            dst = dst_root / s
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(packs / s, dst)
        of.call([ctx.bpy, of.TOOLS / "explode2" / "piece_icons.py", packs, ICONS / "_tmp", *slots], ok="ICONS_OK",
                show=False)
        for s in slots:
            shutil.move(str(ICONS / "_tmp" / f"{s}.png"), ICONS / f"{pack}_{s}.png")
        shutil.rmtree(ICONS / "_tmp", ignore_errors=True)
    entries = [item(character, outfit, pack, s) for s in slots]
    old = json.loads(ITEMS.read_text(encoding="utf-8")) if ITEMS.is_file() else []
    keep = [e for e in old if e.get("outfit") != f"{character}/{outfit}"]
    ITEMS.write_text(json.dumps(keep + entries, indent=1), encoding="utf-8")
    print(f"  {len(entries)} items: {', '.join(e['item_id'] for e in entries)}")
    return {"items": [e["item_id"] for e in entries], "meshes": str(dst_root)}


def main(argv=None) -> None:
    args = list(argv or sys.argv[1:])
    items_only = "--items-only" in args
    character, outfit = [a for a in args if not a.startswith("--")][:2]
    print("EQUIP_INSTALL_OK", json.dumps(install(character, outfit, items_only)))


if __name__ == "__main__":
    main()
