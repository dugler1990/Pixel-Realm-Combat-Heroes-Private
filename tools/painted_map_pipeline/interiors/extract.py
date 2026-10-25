"""Furnishing, step 3: each variant's sheet cut into the shared prop set, and tagged.

By hand this was `extract-props` run on the Leonardo downloads, then props.json filled in
by hand -- name, category, mount -- before any of it could be placed. The cutting is the same
`props.extract_sheet`, now reading the sheet's own background (magenta, not black). What is
new is what it remembers:

  - `vNN/extracted.json`: which props this variant's sheet produced -- the ones step 4
    looks for in this variant's room;
  - the sheet's entry in props.json says `from: <building>/vNN`.

The tags are asked of a model that can see them (the numbered contact sheet, through
`claude -p` like the wall thickness), and only for props nobody has named: a name typed at the
gate or in props.json is never overwritten. A failed question leaves the props untagged and
says so -- a missing tag is filled in at the gate, it does not stop the walk.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from PIL import Image

from tools.sprite_assets import props as props_mod

from . import kit as kit_mod
from .ask_model import WallThicknessError, claude_cli

EXTRACTED = "extracted.json"
# What the tags may say. Free text would scatter one thing over five spellings, and the
# category is what Tiled filters on.
CATEGORIES = ("statue", "brazier", "torch", "urn", "chest", "treasure", "table", "altar",
              "sarcophagus", "throne", "pillar", "banner", "relief", "furniture", "other")
MOUNTS = ("floor", "wall")


def set_dir(spec) -> Path:
    return kit_mod.prop_set_dir(spec)


def load_catalog(spec) -> dict:
    folder = set_dir(spec)
    folder.mkdir(parents=True, exist_ok=True)
    return props_mod.load_catalog(folder, folder.name)


def save_catalog(spec, catalog: dict) -> Path:
    return props_mod.save_catalog(set_dir(spec), catalog)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def extracted(variant) -> dict:
    """What step 3 recorded for this variant, or {} before it has run."""
    return _read_json(variant.folder / EXTRACTED)


def is_current(state) -> bool:
    """Has this variant's current sheet been cut? (A redrawn sheet has to be cut again.)"""
    record = extracted(state.variant)
    return bool(record) and state.drawn and record.get("sheet_sha1") == kit_mod.file_sha1(state.sheet)


def extract_variant(spec, state, catalog: dict) -> dict:
    """Cut `state`'s sheet into the set, record which props it produced. Returns the record.

    When the variant was cut before from a different sheet -- its sheet was redrawn -- the
    props of that earlier sheet are struck (`keep: false`): it was redrawn because it was
    wrong. Striking is not deleting; `[u <ids>]` at the gate brings one back.
    """
    folder = set_dir(spec)
    previous = extracted(state.variant)
    source = f"{spec.building}/{state.tag}"
    props = props_mod.extract_sheet(catalog, state.sheet, folder, source=source)
    sheet_sha1 = kit_mod.file_sha1(state.sheet)
    key = next(e["key"] for e in catalog["sheets"] if e["sha1"] == sheet_sha1)
    if previous.get("sheet") and previous["sheet"] != key:
        struck = [p["id"] for p in catalog["props"]
                  if p["sheet"] == previous["sheet"] and p.get("keep", True)]
        for prop in catalog["props"]:
            if prop["id"] in struck:
                prop["keep"] = False
        if struck:
            print(f"  {state.tag}: struck {len(struck)} prop(s) of its earlier sheet "
                  f"{previous['sheet']} -- [u <ids>] brings one back")
    record = {"sheet": key, "sheet_sha1": sheet_sha1, "props": [
        {"id": prop["id"], "tile_id": prop["tile_id"], "sheet_box": prop["source_box"]}
        for prop in props]}
    (state.variant.folder / EXTRACTED).write_text(json.dumps(record, indent=2) + "\n",
                                                  encoding="utf-8")
    return record


def contact_sheet(spec, key: str) -> Path:
    return set_dir(spec) / f"_contact_{key}.png"


def props_of(catalog: dict, key: str) -> list:
    return [p for p in catalog["props"] if p["sheet"] == key]


def refresh_contact(spec, catalog: dict, key: str) -> Path:
    return props_mod.write_contact_sheet(props_of(catalog, key), set_dir(spec),
                                         contact_sheet(spec, key))


# ---------------------------------------------------------------- tags

def _tag_question(sheet: Path, ids: list, subject: str) -> str:
    return (
        f"Read the image at {Path(sheet).resolve()}\n\n"
        f"It is a contact sheet of game props cut from a sprite sheet: things that stand inside "
        f"a {subject}, seen from above at a three-quarter angle. The id under each picture "
        f"names it. Tag these ids: {', '.join(ids)}.\n\n"
        f"For each give a name of two to four words, a category -- one of "
        f"{', '.join(CATEGORIES)} -- and a mount: wall if it hangs on a wall or is fixed flat "
        f"against one (a banner, a relief, a sconce, a wall panel), floor if it stands on the "
        f"floor.\n\n"
        f'Answer with JSON only, a list like [{{"id": "s10_00", "name": "anubis statue", '
        f'"category": "statue", "mount": "floor"}}]. No other text.'
    )


def parse_tags(text: str) -> dict:
    """id -> {name, category, mount}, from the model's reply. Unknown values are dropped."""
    found = re.search(r"\[.*\]", text or "", re.S)
    if not found:
        raise ValueError(f"no JSON list in the reply: {(text or '')[:200]!r}")
    out = {}
    for item in json.loads(found.group()):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        tag = {"name": str(item.get("name", "")).strip().lower()[:40]}
        category = str(item.get("category", "")).strip().lower()
        tag["category"] = category if category in CATEGORIES else "other"
        mount = str(item.get("mount", "")).strip().lower()
        tag["mount"] = mount if mount in MOUNTS else "floor"
        out[str(item["id"]).strip()] = tag
    return out


def ask_tags(sheet: Path, ids: list, subject: str, timeout: int = 300) -> dict:
    """The model's tags for `ids` on the contact sheet `sheet`. Raises RuntimeError on failure."""
    command = [str(claude_cli()), "-p", _tag_question(sheet, ids, subject),
               "--allowed-tools", "Read", "--output-format", "text"]
    print(f"  asking for tags of {len(ids)} prop(s) on {Path(sheet).name} ...", flush=True)
    try:
        finished = subprocess.run(command, timeout=timeout, capture_output=True, text=True)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"the tag question timed out after {timeout}s") from exc
    if finished.returncode != 0:
        raise RuntimeError(f"claude -p failed ({finished.returncode}): {finished.stderr[:500]}")
    return parse_tags(finished.stdout)


def untagged(props: list) -> list:
    return [p for p in props if not p.get("name")]


def tag_variant(spec, catalog: dict, key: str, ask=ask_tags) -> int:
    """Fill in the tags of this sheet's unnamed props. Returns how many were tagged.

    `ask` is the question, swappable so the walk can be tested without a model. A failure
    is reported and leaves the props as they were.
    """
    todo = untagged(props_of(catalog, key))
    if not todo:
        return 0
    sheet = refresh_contact(spec, catalog, key)
    try:
        tags = ask(sheet, [p["id"] for p in todo], spec.object_prompt or "building")
    except (RuntimeError, ValueError, OSError, WallThicknessError) as exc:
        print(f"  could not tag {key}: {exc} -- tag them at the gate with [t ...]")
        return 0
    count = 0
    for prop in todo:
        tag = tags.get(prop["id"])
        if tag:
            prop.update(tag, tagged="model")
            count += 1
    refresh_contact(spec, catalog, key)
    return count


def set_tag(prop: dict, category: str, mount: str, name: str = "") -> str:
    """`[t <id> <category> <mount> [name]]` at the gate. Returns what is wrong, or ""."""
    category, mount = category.lower(), mount.lower()
    if category not in CATEGORIES:
        return f"category is one of: {', '.join(CATEGORIES)}"
    if mount not in MOUNTS:
        return "mount is floor or wall"
    prop.update(category=category, mount=mount, tagged="hand")
    if name:
        prop["name"] = name.strip().lower()
    return ""


def extract_strip(spec, rows: list, out_path: Path) -> Path:
    """Every variant's contact sheet stacked, each under a label: the one picture to review."""
    from PIL import ImageDraw

    from .decorate import _font
    from .trace import save_image

    font = _font(18)
    pictures = []
    for label, path in rows:
        picture = Image.open(path).convert("RGB") if path and Path(path).exists() else None
        pictures.append((label, picture))
    width = max([p.width for _l, p in pictures if p is not None] + [600])
    height = sum(30 + (p.height if p is not None else 0) + 10 for _l, p in pictures)
    sheet = Image.new("RGB", (width, max(1, height)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for label, picture in pictures:
        draw.text((6, y + 5), label, fill=(255, 220, 90), font=font)
        y += 30
        if picture is not None:
            sheet.paste(picture, (0, y))
            y += picture.height
        y += 10
    return save_image(sheet, out_path)
