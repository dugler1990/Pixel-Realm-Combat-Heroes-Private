"""The outfit pipeline's last step, `install`: the outfit into the game (outfit.py runs it; PROCESS_outfit.md).

armour, cut   every piece needs its stats first: the bases its items will name (equipment.piece_base: the outfit's
              "material" + the piece) must be in Graphics/Standard_Items/item_bases.json. Missing ones stop the step
              (the page's form writes them: add_bases). Then equip_install.py: packs, icons, items with "base".
body          the hero entry (export_outfit.hero_entry + the outfit's start_equipment) is shown at a gate; accepted,
              it is appended to Graphics/PlayerSelectionDict.json at a free selection position.
The two repo files are hand-formatted: entries are appended as text (the rest of the file is left as it is) and the
result is parsed before it is written. You review and commit them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CODE = REPO / "Code"
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))
import equipment  # noqa: E402
import item_properties as IP  # noqa: E402

BASES = Path(IP.BASES_PATH).resolve()
SELECTION = Path(equipment.SELECTION).resolve()


def slots(ctx) -> list[str]:
    """The pieces the export made (<run>/packs/slot_packs.json)."""
    info = ctx.work / "packs" / "slot_packs.json"
    if not info.is_file():
        raise SystemExit(f"no {info}: run export first")
    return sorted(json.loads(info.read_text(encoding="utf-8")))


def needed_bases(ctx) -> list[str]:
    return sorted({equipment.piece_base(s, ctx.o.get("material")) for s in slots(ctx) if s in equipment.PIECES})


def missing_bases(ctx) -> list[str]:
    have = IP.load_bases(BASES)
    return [b for b in needed_bases(ctx) if b not in have]


def base_problems(base_id: str, base: dict) -> list[str]:
    out = [f"{base_id}: unknown field {k!r}" for k in IP.unknown_fields(base)]
    for k, v in base.items():
        p = IP.BY_ID.get(k)
        if p is None:
            continue
        if p.format == "list" and not (isinstance(v, list) and set(v) <= set(IP.REGIONS)):
            out.append(f"{base_id}: {k} must be a list of {list(IP.REGIONS)}")
        elif p.format == "yes-no" and not isinstance(v, bool):
            out.append(f"{base_id}: {k} must be true or false")
        elif p.format in ("int", "number", "percent") and (isinstance(v, bool) or not isinstance(v, (int, float))):
            out.append(f"{base_id}: {k} must be a number")
        elif p.format == "percent" and not 0 <= v <= 1:
            out.append(f"{base_id}: {k} is a share, 0 to 1")
    if not base.get("name"):
        out.append(f"{base_id}: no name")
    return out


def _append(path: Path, text_for, data_check) -> None:
    """Insert text before the closing bracket of a hand-formatted JSON file; parse the result; write it."""
    raw = path.read_bytes().decode("utf-8")
    nl = "\r\n" if "\r\n" in raw else "\n"
    new = text_for(raw, nl)
    data_check(json.loads(new))
    path.write_bytes(new.encode("utf-8"))


def add_bases(bases: dict, path: Path = BASES) -> list[str]:
    """Append new bases to item_bases.json (one line of fields each). Refuses ids already there and bad fields."""
    have = IP.load_bases(path)
    bad = [f"{b}: already in item_bases.json" for b in bases if b in have]
    bad += [p for b, base in bases.items() for p in base_problems(b, base)]
    if bad:
        raise ValueError("; ".join(bad))

    def text(raw, nl):
        end = raw.rstrip().rfind("}")
        body = "".join(f",{nl} {json.dumps(b)}: {json.dumps(base, ensure_ascii=False)}" for b, base in bases.items())
        return raw[:end].rstrip() + body + nl + raw[end:]
    def check(data):
        if any(data.get(b) != base for b, base in bases.items()):
            raise ValueError(f"appending to {path.name} went wrong: nothing written")
    _append(path, text, check)
    return sorted(bases)


def hero(ctx) -> dict:
    from tools.boss_sprite_pipeline import export_outfit as eo
    entry = eo.hero_entry(ctx.o, ctx)
    if ctx.o.get("start_equipment"):
        entry["start_equipment"] = ctx.o["start_equipment"]
    return entry


def listed(entry: dict, path: Path = SELECTION) -> dict | None:
    players = json.loads(path.read_text(encoding="utf-8"))["Players"]
    return next((p for p in players if p.get("mesh_pack") == entry["mesh_pack"]), None)


def add_hero(entry: dict, path: Path = SELECTION) -> dict:
    """Append the hero to PlayerSelectionDict.json at the first free x of row 0."""
    players = json.loads(path.read_text(encoding="utf-8"))["Players"]
    if any(p.get("mesh_pack") == entry["mesh_pack"] or p.get("name") == entry["name"] for p in players):
        raise ValueError(f"{entry['name']} / {entry['mesh_pack']} is already in {path.name}")
    used = {(p["selection_position"]["x"], p["selection_position"]["y"]) for p in players if "selection_position" in p}
    entry = {**entry, "selection_position": {"x": next(x for x in range(len(used) + 1) if (x, 0) not in used), "y": 0}}

    def text(raw, nl):
        end = raw.rfind("]")
        block = json.dumps(entry, indent=4, ensure_ascii=False).replace("\n", nl + "        ")
        return raw[:end].rstrip() + "," + nl + nl + "        " + block + nl + "    " + raw[end:]
    def check(data):
        if data["Players"][-1] != entry:
            raise ValueError(f"appending to {path.name} went wrong: nothing written")
    _append(path, text, check)
    return entry
