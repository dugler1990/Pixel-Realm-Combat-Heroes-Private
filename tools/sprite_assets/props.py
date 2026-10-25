"""Prop catalogue: objects cut from AI prop sheets, logged in props.json, served to Tiled.

One folder per prop set (e.g. ``Graphics/Props/pyramid``):

    _sheets/s01.jpg …          the source sheets, copied in so a re-run needs nothing else
    s01_00.png …               one transparent PNG per object
    props.json                 the catalogue (see below)
    pyramid_props.tsx          Tiled image-collection tileset of every prop with keep=true
    _contact_s01.png …         numbered previews for review, struck-out props crossed
    _debug/s01_overlay.png …   each sheet with what was found boxed and labelled

A prop's ``tile_id`` is handed out once and never reused: maps place props by tile id,
so re-running the extraction or dropping a prop must not shift the others. Re-running
also keeps what was filled in by hand (name, category, mount, keep).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw

from tools.sprite_assets.cut_sheet import find_objects, save_debug_overlay
from tools.sprite_assets.remove_bg import matte_object, trim_box

CATALOG_NAME = "props.json"
SHEETS_DIR = "_sheets"
HAND_FIELDS = ("name", "category", "mount", "keep")
SAME_OBJECT_IOU = 0.7


def load_catalog(out_dir: Path, set_name: str) -> dict:
    path = Path(out_dir) / CATALOG_NAME
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"set": set_name, "next_tile_id": 0, "sheets": [], "props": []}


def save_catalog(out_dir: Path, catalog: dict) -> Path:
    path = Path(out_dir) / CATALOG_NAME
    path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return path


def _iou(a: list[int], b: list[int]) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def _register_sheet(catalog: dict, sheet: Path, out_dir: Path) -> dict:
    """The catalogue's entry for this sheet, copying it into _sheets/ the first time."""
    sha1 = hashlib.sha1(sheet.read_bytes()).hexdigest()
    for entry in catalog["sheets"]:
        if entry["sha1"] == sha1:
            return entry
    taken = {e["key"] for e in catalog["sheets"]}
    n = len(catalog["sheets"]) + 1
    while f"s{n:02d}" in taken:
        n += 1
    key = f"s{n:02d}"
    dest = Path(out_dir) / SHEETS_DIR / f"{key}{sheet.suffix.lower()}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sheet, dest)
    entry = {"key": key, "file": dest.relative_to(out_dir).as_posix(),
             "source_name": sheet.name, "sha1": sha1}
    catalog["sheets"].append(entry)
    return entry


def extract_sheet(catalog: dict, sheet: Path, out_dir: Path, source: str = "") -> list[dict]:
    """Cut every object off one sheet into out_dir and log it; returns this sheet's props.

    ``source`` is where the sheet came from when it was not a download -- the furnishing
    walkthrough passes ``<building>/vNN`` -- and is kept on the sheet's entry as ``from``.
    """
    out_dir = Path(out_dir)
    entry = _register_sheet(catalog, Path(sheet), out_dir)
    if source:
        entry["from"] = source
    key = entry["key"]
    image = Image.open(out_dir / entry["file"]).convert("RGB")
    found = find_objects(image, prefix=key)
    save_debug_overlay(image, [f.cell for f in found], out_dir / "_debug" / f"{key}_overlay.png",
                       labels=True)

    earlier = [p for p in catalog["props"] if p["sheet"] == key]
    taken_ids = {p["id"] for p in catalog["props"]}
    claimed: set[str] = set()
    props: list[dict] = []
    for obj in found:
        box = list(obj.cell.box)
        matted = matte_object(image.crop(obj.cell.box), obj.mask, black_thr=obj.black_thr,
                              background=obj.background)
        trim = trim_box(matted, pad=1)
        cut = matted.crop(trim)
        match = max(
            (p for p in earlier if p["id"] not in claimed),
            key=lambda p: _iou(p["source_box"], box),
            default=None,
        )
        if match is not None and _iou(match["source_box"], box) >= SAME_OBJECT_IOU:
            prop = match
        else:
            prop_id = obj.cell.name
            n = 0
            while prop_id in taken_ids:
                n += 1
                prop_id = f"{obj.cell.name}_{n}"
            prop = {"id": prop_id, "tile_id": catalog["next_tile_id"], "sheet": key,
                    "name": "", "category": "", "mount": "floor", "keep": True}
            catalog["next_tile_id"] += 1
            catalog["props"].append(prop)
            taken_ids.add(prop_id)
        claimed.add(prop["id"])
        prop["file"] = f"{prop['id']}.png"
        prop["source_box"] = box
        # Where the cut-out itself sits on the sheet: what a prop is placed by.
        prop["image_box"] = [box[0] + trim[0], box[1] + trim[1], box[0] + trim[2], box[1] + trim[3]]
        prop["size"] = list(cut.size)
        cut.save(out_dir / prop["file"])
        props.append(prop)

    lost = [p["id"] for p in earlier if p["id"] not in claimed]
    if lost:
        print(f"  {key}: {len(lost)} props from an earlier run not found again, kept: {lost}")
    write_contact_sheet(props, out_dir, out_dir / f"_contact_{key}.png")
    return props


def write_contact_sheet(props: Iterable[dict], out_dir: Path, path: Path, *,
                        cols: int = 10, cell: int = 128, label_h: int = 14) -> Path:
    """Numbered previews: each prop's id under its thumbnail; struck-out props crossed.

    On white, where a hole or a fringe in a cut-out shows; black would hide it. Once props
    are tagged, a second line under each says its category, and "wall" for a wall mount.
    """
    props = list(props)
    cols = max(1, min(cols, len(props)))
    rows = max(1, (len(props) + cols - 1) // cols)
    pad = 4
    tags = [", ".join(t for t in (p.get("category", ""),
                                  "wall" if p.get("mount") == "wall" else "") if t)
            for p in props]
    if any(tags):
        label_h *= 2
    step_x, step_y = cell + pad, cell + label_h + pad
    sheet = Image.new("RGBA", (cols * step_x + pad, rows * step_y + pad), (255, 255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for i, prop in enumerate(props):
        r, c = divmod(i, cols)
        x, y = pad + c * step_x, pad + r * step_y
        thumb = Image.open(Path(out_dir) / prop["file"]).convert("RGBA")
        thumb.thumbnail((cell - 2, cell - 2), Image.Resampling.LANCZOS)
        sheet.paste(thumb, (x + (cell - thumb.width) // 2, y + (cell - thumb.height) // 2), thumb)
        draw.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(200, 200, 205, 255))
        label = prop["id"] + (f" {prop['name']}" if prop.get("name") else "")
        draw.text((x + 2, y + cell + 1), label[:22], fill=(30, 30, 30, 255))
        if tags[i]:
            draw.text((x + 2, y + cell + 1 + label_h // 2), tags[i][:22], fill=(90, 90, 160, 255))
        if not prop.get("keep", True):
            draw.line([x, y, x + cell - 1, y + cell - 1], fill=(220, 40, 40, 255), width=3)
            draw.line([x, y + cell - 1, x + cell - 1, y], fill=(220, 40, 40, 255), width=3)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path


def write_tileset(out_dir: Path, catalog: dict) -> Path:
    """Tiled image-collection tileset of every kept prop, keyed by its fixed tile_id.

    Each tile carries prop_id, name and mount as properties (pytmx copies them onto every
    object placed from it) and its category as the tile's type, so props are easy to find
    and filter in Tiled.
    """
    out_dir = Path(out_dir)
    kept = sorted((p for p in catalog["props"] if p.get("keep", True)), key=lambda p: p["tile_id"])
    name = f"{catalog['set']}_props"
    root = ET.Element("tileset", {
        "version": "1.10", "tiledversion": "1.11.0", "name": name,
        "tilewidth": str(max((p["size"][0] for p in kept), default=1)),
        "tileheight": str(max((p["size"][1] for p in kept), default=1)),
        "tilecount": str(len(kept)), "columns": "0",
    })
    ET.SubElement(root, "grid", {"orientation": "orthogonal", "width": "1", "height": "1"})
    for prop in kept:
        attrs = {"id": str(prop["tile_id"])}
        if prop.get("category"):
            attrs["type"] = prop["category"]
        tile = ET.SubElement(root, "tile", attrs)
        properties = ET.SubElement(tile, "properties")
        for key in ("prop_id", "name", "mount"):
            value = prop["id"] if key == "prop_id" else prop.get(key, "")
            if value:
                ET.SubElement(properties, "property", {"name": key, "value": str(value)})
        ET.SubElement(tile, "image", {
            "width": str(prop["size"][0]), "height": str(prop["size"][1]), "source": prop["file"],
        })
    ET.indent(root, space=" ")
    path = out_dir / f"{name}.tsx"
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)
    return path


def refresh_contact_sheets(out_dir: Path, catalog: dict) -> None:
    for entry in catalog["sheets"]:
        props = [p for p in catalog["props"] if p["sheet"] == entry["key"]]
        if props:
            write_contact_sheet(props, out_dir, Path(out_dir) / f"_contact_{entry['key']}.png")
