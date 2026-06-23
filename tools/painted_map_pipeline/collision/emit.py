"""Emit collision artifacts and optional TMX fragments for one chunk."""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def chunk_entry(manifest: dict[str, Any], chunk_id: str) -> dict[str, Any]:
    for chunk in manifest.get("chunks", []):
        if chunk.get("chunk_id") == chunk_id:
            return chunk
    raise KeyError(f"chunk {chunk_id!r} not found in manifest")


def _relative_to(path: Path, base_file: Path) -> str:
    return os.path.relpath(path, start=base_file.parent).replace(os.sep, "/")


def painted_grid_origin_from_tmx(map_path: Path) -> tuple[float, float, float, float]:
    """Infer (origin_x, origin_y, cell_w, cell_h) from PaintedGround objects."""
    root = ET.parse(map_path).getroot()
    objects = []
    for node in root:
        if node.tag == "objectgroup" and node.attrib.get("name", "").lower() == "paintedground":
            for obj in node.findall("object"):
                objects.append(
                    (
                        float(obj.attrib["x"]),
                        float(obj.attrib["y"]),
                        float(obj.attrib.get("width", "0")),
                        float(obj.attrib.get("height", "0")),
                    )
                )
    if not objects:
        raise ValueError(f"No PaintedGround objects in {map_path}")
    objects.sort(key=lambda item: (item[1], item[0]))
    origin_x, origin_y, cell_w, cell_h = objects[0]
    if cell_w <= 0 or cell_h <= 0:
        cell_w, cell_h = objects[1][0] - origin_x, objects[1][1] - origin_y
    return origin_x, origin_y, cell_w, cell_h


def tmx_placement_for_chunk(
    chunk: dict[str, Any],
    manifest: dict[str, Any],
    *,
    reference_tmx: Path | None = None,
) -> tuple[float, float, float, float]:
    """Return (x, y, width, height) in TMX object coordinates."""
    grid = chunk.get("grid") or [0, 0]
    col, row = int(grid[0]), int(grid[1])
    chunk_size = manifest.get("chunk_size_px") or chunk.get("image_size") or [5056, 3392]
    cw, ch = float(chunk_size[0]), float(chunk_size[1])

    if reference_tmx is not None and reference_tmx.exists():
        ox, oy, rw, rh = painted_grid_origin_from_tmx(reference_tmx)
        if rw > 0:
            cw = rw
        if rh > 0:
            ch = rh
        return ox + col * cw, oy + row * ch, cw, ch

    world_rect = chunk.get("world_rect")
    if world_rect and len(world_rect) == 4:
        return float(world_rect[0]), float(world_rect[1]), cw, ch

    raise ValueError("Need reference_tmx or chunk world_rect for placement")


def write_collision_tileset(tsx_path: Path, image_path: Path, image_size: tuple[int, int]) -> None:
    root = ET.Element(
        "tileset",
        {
            "version": "1.10",
            "tiledversion": "1.11.0",
            "name": "collision_chunks",
            "tilewidth": str(image_size[0]),
            "tileheight": str(image_size[1]),
            "tilecount": "1",
            "columns": "0",
        },
    )
    ET.SubElement(root, "grid", {"orientation": "orthogonal", "width": "1", "height": "1"})
    tile = ET.SubElement(root, "tile", {"id": "0"})
    ET.SubElement(
        tile,
        "image",
        {
            "width": str(image_size[0]),
            "height": str(image_size[1]),
            "source": _relative_to(image_path.resolve(), tsx_path.resolve()),
        },
    )
    ET.indent(root, space=" ")
    ET.ElementTree(root).write(tsx_path, encoding="utf-8", xml_declaration=True)


def write_collision_fragment(
    fragment_path: Path,
    *,
    layer_name: str,
    x: float,
    y: float,
    width: float,
    height: float,
    gid: int,
    object_id: int = 1,
    layer_id: int = 9001,
) -> None:
    root = ET.Element(
        "objectgroup",
        {
            "id": str(layer_id),
            "name": layer_name,
        },
    )
    ET.SubElement(
        root,
        "object",
        {
            "id": str(object_id),
            "gid": str(gid),
            "x": str(int(round(x))),
            "y": str(int(round(y))),
            "width": str(int(round(width))),
            "height": str(int(round(height))),
        },
    )
    ET.indent(root, space=" ")
    ET.ElementTree(root).write(fragment_path, encoding="utf-8", xml_declaration=True)


def write_preview_map(
    map_path: Path,
    *,
    map_width_px: int,
    map_height_px: int,
    tile_size: int,
    painted_image: Path | None,
    painted_placement: tuple[float, float, float, float] | None,
    collision_tsx: Path,
    collision_placement: tuple[float, float, float, float],
    collision_gid: int = 1,
) -> None:
    """Minimal standalone TMX for reviewing painted art + collision in Tiled."""
    cols = max(1, int((map_width_px + tile_size - 1) // tile_size))
    rows = max(1, int((map_height_px + tile_size - 1) // tile_size))
    root = ET.Element(
        "map",
        {
            "version": "1.8",
            "tiledversion": "1.8.0",
            "orientation": "orthogonal",
            "renderorder": "right-down",
            "width": str(cols),
            "height": str(rows),
            "tilewidth": str(tile_size),
            "tileheight": str(tile_size),
            "infinite": "0",
            "nextlayerid": "4",
            "nextobjectid": "10",
        },
    )
    ET.SubElement(
        root,
        "tileset",
        {"firstgid": str(collision_gid), "source": _relative_to(collision_tsx.resolve(), map_path.resolve())},
    )

    if painted_image is not None and painted_placement is not None:
        painted_tsx = map_path.parent / "preview_painted.tsx"
        with Image.open(painted_image) as img:
            write_collision_tileset(painted_tsx, painted_image, img.size)
        painted_gid = collision_gid + 1
        ET.SubElement(
            root,
            "tileset",
            {"firstgid": str(painted_gid), "source": _relative_to(painted_tsx.resolve(), map_path.resolve())},
        )
        pg = ET.SubElement(root, "objectgroup", {"id": "1", "name": "PaintedGround"})
        px, py, pw, ph = painted_placement
        ET.SubElement(
            pg,
            "object",
            {
                "id": "1",
                "gid": str(painted_gid),
                "x": str(int(round(px))),
                "y": str(int(round(py))),
                "width": str(int(round(pw))),
                "height": str(int(round(ph))),
            },
        )

    cx, cy, cw, ch = collision_placement
    og = ET.SubElement(root, "objectgroup", {"id": "2", "name": "PaintedCollision"})
    ET.SubElement(
        og,
        "object",
        {
            "id": "2",
            "gid": str(collision_gid),
            "x": str(int(round(cx))),
            "y": str(int(round(cy))),
            "width": str(int(round(cw))),
            "height": str(int(round(ch))),
        },
    )
    ET.indent(root, space=" ")
    ET.ElementTree(root).write(map_path, encoding="utf-8", xml_declaration=True)


def write_result_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
