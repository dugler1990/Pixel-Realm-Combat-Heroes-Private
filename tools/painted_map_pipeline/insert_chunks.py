from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from PIL import Image


def _remove_existing_painted_ground(root: ET.Element):
    for node in list(root):
        if node.tag == "objectgroup" and node.attrib.get("name", "").lower() == "paintedground":
            root.remove(node)


def _next_layer_id(root: ET.Element):
    max_id = 0
    for node in root:
        raw = node.attrib.get("id")
        if raw:
            try:
                max_id = max(max_id, int(raw))
            except ValueError:
                pass
    return max_id + 1


def _next_object_id(root: ET.Element):
    raw = root.attrib.get("nextobjectid")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def _parse_csv_data(text):
    return [int(part) for part in re.split(r"\s*,\s*", (text or "").strip()) if part.strip()]


def _next_firstgid(root: ET.Element):
    max_gid = 0
    for layer in root.findall("layer"):
        data = layer.find("data")
        if data is None:
            continue
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


def _relative_to(path: Path, base_file: Path):
    return os.path.relpath(path, start=base_file.parent).replace(os.sep, "/")


def _remove_existing_painted_tileset(root: ET.Element):
    for node in list(root):
        if node.tag == "tileset" and node.attrib.get("source") == "painted_chunks.tsx":
            root.remove(node)


def _write_painted_tileset(output_tmx_path: Path, chunk_entries: list[dict]):
    tsx_path = output_tmx_path.parent / "painted_chunks.tsx"
    max_w = max((int(chunk["image_size"][0]) for chunk in chunk_entries), default=1)
    max_h = max((int(chunk["image_size"][1]) for chunk in chunk_entries), default=1)
    root = ET.Element(
        "tileset",
        {
            "version": "1.10",
            "tiledversion": "1.11.0",
            "name": "painted_chunks",
            "tilewidth": str(max_w),
            "tileheight": str(max_h),
            "tilecount": str(len(chunk_entries)),
            "columns": "0",
        },
    )
    ET.SubElement(root, "grid", {"orientation": "orthogonal", "width": "1", "height": "1"})
    for idx, chunk in enumerate(chunk_entries):
        tile = ET.SubElement(root, "tile", {"id": str(idx)})
        ET.SubElement(
            tile,
            "image",
            {
                "width": str(int(chunk["image_size"][0])),
                "height": str(int(chunk["image_size"][1])),
                "source": _relative_to(Path(chunk["painted_image"]).resolve(), tsx_path.resolve()),
            },
        )
    ET.indent(root, space=" ")
    ET.ElementTree(root).write(tsx_path, encoding="utf-8", xml_declaration=True)
    return tsx_path


def insert_painted_chunks(tmx_path, chunks_manifest_path, output_tmx_path):
    tmx_path = Path(tmx_path)
    chunks_manifest_path = Path(chunks_manifest_path)
    output_tmx_path = Path(output_tmx_path)
    root = ET.parse(tmx_path).getroot()
    manifest = json.loads(chunks_manifest_path.read_text(encoding="utf-8"))

    _remove_existing_painted_ground(root)
    _remove_existing_painted_tileset(root)
    firstgid = _next_firstgid(root)
    chunk_entries = []
    for chunk in manifest.get("chunks", []):
        image_path = Path(chunk["painted_image"])
        if not image_path.exists():
            continue
        with Image.open(image_path) as image:
            image_size = image.size
        entry = dict(chunk)
        entry["image_size"] = list(image_size)
        chunk_entries.append(entry)
    _write_painted_tileset(output_tmx_path, chunk_entries)
    tilesets = [node for node in root if node.tag == "tileset"]
    root_children = list(root)
    insert_tileset_at = root_children.index(tilesets[-1]) + 1 if tilesets else 0
    root.insert(
        insert_tileset_at,
        ET.Element("tileset", {"firstgid": str(firstgid), "source": "painted_chunks.tsx"}),
    )

    layer = ET.Element(
        "objectgroup",
        {
            "id": str(_next_layer_id(root)),
            "name": "PaintedGround",
        },
    )

    object_id = _next_object_id(root)
    inserted = []
    for idx, chunk in enumerate(chunk_entries):
        image_x, image_y, world_w, world_h = chunk.get(
            "source_rect_with_overlap", chunk["world_rect"]
        )
        obj = ET.SubElement(
            layer,
            "object",
            {
                "id": str(object_id),
                "gid": str(firstgid + idx),
                "x": str(int(image_x)),
                "y": str(int(image_y + world_h)),
                "width": str(int(world_w)),
                "height": str(int(world_h)),
            },
        )
        object_id += 1
        inserted.append(chunk["chunk_id"])

    # Put PaintedGround before gameplay object layers but after tilesets/tile layers.
    insert_at = len(root)
    for idx, node in enumerate(list(root)):
        if node.tag == "objectgroup":
            insert_at = idx
            break
    root.insert(insert_at, layer)
    root.attrib["nextobjectid"] = str(object_id)
    root.attrib["nextlayerid"] = str(max(_next_layer_id(root), int(root.attrib.get("nextlayerid", 1))))

    ET.indent(root, space=" ")
    output_tmx_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(output_tmx_path, encoding="utf-8", xml_declaration=True)
    return {"output_tmx": str(output_tmx_path), "inserted_chunks": inserted}

