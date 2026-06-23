"""Merge Leonardo collision sprites from collision_trial into expanse map.tmx."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from .emit import load_manifest, tmx_placement_for_chunk


def _relative_to(path: Path, base_file: Path) -> str:
    return os.path.relpath(path, start=base_file.parent).replace(os.sep, "/")


def _parse_csv_data(text):
    return [int(part) for part in re.split(r"\s*,\s*", (text or "").strip()) if part.strip()]


def _next_firstgid(root: ET.Element) -> int:
    max_gid = 0
    for layer in root.findall("layer"):
        data = layer.find("data")
        if data is not None and data.text:
            for gid in _parse_csv_data(data.text):
                max_gid = max(max_gid, gid & 0x1FFFFFFF)
    for objectgroup in root.findall("objectgroup"):
        for obj in objectgroup.findall("object"):
            raw = obj.attrib.get("gid")
            if raw:
                try:
                    max_gid = max(max_gid, int(raw) & 0x1FFFFFFF)
                except ValueError:
                    pass
    return max_gid + 1


def _next_layer_id(root: ET.Element) -> int:
    max_id = 0
    for node in root:
        raw = node.attrib.get("id")
        if raw:
            try:
                max_id = max(max_id, int(raw))
            except ValueError:
                pass
    return max_id + 1


def _next_object_id(root: ET.Element) -> int:
    max_id = 0
    for objectgroup in root.findall("objectgroup"):
        for obj in objectgroup.findall("object"):
            raw = obj.attrib.get("id")
            if raw:
                try:
                    max_id = max(max_id, int(raw))
                except ValueError:
                    pass
    raw = root.attrib.get("nextobjectid")
    try:
        max_id = max(max_id, int(raw) - 1)
    except (TypeError, ValueError):
        pass
    return max_id + 1


def _remove_collision_layer(root: ET.Element) -> None:
    for node in list(root):
        if node.tag == "objectgroup" and node.attrib.get("name") == "PaintedCollision":
            root.remove(node)


def _remove_collision_tileset(root: ET.Element) -> None:
    for node in list(root):
        if node.tag == "tileset" and node.attrib.get("source") == "collision_chunks.tsx":
            root.remove(node)


def _write_collision_tileset(tsx_path: Path, entries: list[dict]) -> None:
    max_w = max((int(e["image_size"][0]) for e in entries), default=1)
    max_h = max((int(e["image_size"][1]) for e in entries), default=1)
    root = ET.Element(
        "tileset",
        {
            "version": "1.10",
            "tiledversion": "1.11.0",
            "name": "collision_chunks",
            "tilewidth": str(max_w),
            "tileheight": str(max_h),
            "tilecount": str(len(entries)),
            "columns": "0",
        },
    )
    ET.SubElement(root, "grid", {"orientation": "orthogonal", "width": "1", "height": "1"})
    for idx, entry in enumerate(entries):
        tile = ET.SubElement(root, "tile", {"id": str(idx)})
        ET.SubElement(
            tile,
            "image",
            {
                "width": str(int(entry["image_size"][0])),
                "height": str(int(entry["image_size"][1])),
                "source": _relative_to(Path(entry["collision_image"]).resolve(), tsx_path.resolve()),
            },
        )
    ET.indent(root, space=" ")
    ET.ElementTree(root).write(tsx_path, encoding="utf-8", xml_declaration=True)


def merge_collision_grid(
    *,
    map_path: Path,
    manifest_path: Path,
    collision_trial_root: Path,
    collision_export_dir: Path | None = None,
    layer_name: str = "PaintedCollision",
    variant_subdir: str = "leonardo_direct",
    require_all: bool = False,
) -> dict:
    map_path = Path(map_path).resolve()
    manifest = load_manifest(Path(manifest_path).resolve())
    collision_trial_root = Path(collision_trial_root).resolve()
    export_dir = Path(collision_export_dir or map_path.parent / "export" / "collision_leonardo")
    export_dir.mkdir(parents=True, exist_ok=True)

    root = ET.parse(map_path).getroot()
    reference_tmx = map_path

    entries = []
    missing = []
    for chunk in manifest.get("chunks", []):
        chunk_id = chunk.get("chunk_id") or Path(chunk["painted_image"]).stem
        sprite_src = collision_trial_root / chunk_id / variant_subdir / "collision_sprite.png"
        if not sprite_src.exists():
            missing.append(chunk_id)
            continue
        dest = export_dir / f"{chunk_id}.png"
        shutil.copy2(sprite_src, dest)
        with Image.open(dest) as image:
            image_size = list(image.size)
        x, y, w, h = tmx_placement_for_chunk(chunk, manifest, reference_tmx=reference_tmx)
        entries.append(
            {
                "chunk_id": chunk_id,
                "collision_image": str(dest),
                "image_size": image_size,
                "placement": [x, y, w, h],
            }
        )

    if require_all and missing:
        raise FileNotFoundError(
            f"Missing collision for {len(missing)} chunks (e.g. {missing[:5]}). "
            "Wait for batch to finish or run without --require-all."
        )

    if not entries:
        raise FileNotFoundError(f"No collision sprites found under {collision_trial_root}")

    _remove_collision_layer(root)
    _remove_collision_tileset(root)

    tsx_path = map_path.parent / "collision_chunks.tsx"
    _write_collision_tileset(tsx_path, entries)

    firstgid = _next_firstgid(root)
    tilesets = [node for node in root if node.tag == "tileset"]
    root_children = list(root)
    insert_tileset_at = root_children.index(tilesets[-1]) + 1 if tilesets else 0
    root.insert(
        insert_tileset_at,
        ET.Element("tileset", {"firstgid": str(firstgid), "source": "collision_chunks.tsx"}),
    )

    layer = ET.Element("objectgroup", {"id": str(_next_layer_id(root)), "name": layer_name})
    object_id = _next_object_id(root)
    inserted = []
    for idx, entry in enumerate(entries):
        x, y, w, h = entry["placement"]
        ET.SubElement(
            layer,
            "object",
            {
                "id": str(object_id),
                "gid": str(firstgid + idx),
                "x": str(int(round(x))),
                "y": str(int(round(y))),
                "width": str(int(round(w))),
                "height": str(int(round(h))),
            },
        )
        object_id += 1
        inserted.append(entry["chunk_id"])

    insert_at = len(root)
    for idx, node in enumerate(list(root)):
        if node.tag == "objectgroup" and node.attrib.get("name", "").lower() == "paintedground":
            insert_at = idx + 1
            break
    root.insert(insert_at, layer)

    root.attrib["nextobjectid"] = str(object_id)
    root.attrib["nextlayerid"] = str(max(_next_layer_id(root), int(root.attrib.get("nextlayerid", 1))))

    ET.indent(root, space=" ")
    ET.ElementTree(root).write(map_path, encoding="utf-8", xml_declaration=True)

    summary = {
        "map": str(map_path),
        "collision_tsx": str(tsx_path),
        "collision_export_dir": str(export_dir),
        "inserted_chunks": inserted,
        "inserted_count": len(inserted),
        "missing_chunks": missing,
        "missing_count": len(missing),
    }
    summary_path = export_dir / "merge_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Merge collision trial sprites into map.tmx.")
    parser.add_argument("--map", default="levels/Frostreach/expanse/map.tmx")
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
    )
    parser.add_argument(
        "--collision-trial",
        default="levels/Frostreach/expanse/export/collision_trial",
    )
    parser.add_argument("--require-all", action="store_true", help="Fail if any chunk is missing collision")
    args = parser.parse_args(argv)

    summary = merge_collision_grid(
        map_path=(repo / args.map).resolve(),
        manifest_path=(repo / args.manifest).resolve(),
        collision_trial_root=(repo / args.collision_trial).resolve(),
        require_all=args.require_all,
    )
    print(f"Merged {summary['inserted_count']} chunks into {summary['map']}")
    if summary["missing_count"]:
        print(f"  missing: {summary['missing_count']} chunks (not in map yet)")
    print(f"  summary: {summary['collision_export_dir']}/merge_summary.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
