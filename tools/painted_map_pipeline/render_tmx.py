from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from PIL import Image


GID_MASK = 0x1FFFFFFF


def _resample():
    return getattr(Image, "Resampling", Image).LANCZOS


def _read_int(attrs, key, default=0):
    try:
        return int(attrs.get(key, default))
    except (TypeError, ValueError):
        return default


class TmxTileSource:
    def __init__(self, tmx_path: Path):
        self.tmx_path = Path(tmx_path)
        self.map_root = ET.parse(self.tmx_path).getroot()
        self.map_width = _read_int(self.map_root.attrib, "width")
        self.map_height = _read_int(self.map_root.attrib, "height")
        self.tile_width = _read_int(self.map_root.attrib, "tilewidth")
        self.tile_height = _read_int(self.map_root.attrib, "tileheight")
        self.tilesets = self._load_tilesets()

    @property
    def world_size(self):
        return self.map_width * self.tile_width, self.map_height * self.tile_height

    def _load_tilesets(self):
        tilesets = []
        for ts_node in self.map_root.findall("tileset"):
            firstgid = _read_int(ts_node.attrib, "firstgid")
            ts_path = (self.tmx_path.parent / ts_node.attrib["source"]).resolve()
            ts_root = ET.parse(ts_path).getroot()
            tile_w = _read_int(ts_root.attrib, "tilewidth")
            tile_h = _read_int(ts_root.attrib, "tileheight")
            columns = _read_int(ts_root.attrib, "columns", 0)
            atlas = None
            image_node = ts_root.find("image")
            if image_node is not None:
                atlas_path = (ts_path.parent / image_node.attrib["source"]).resolve()
                if atlas_path.exists():
                    atlas = Image.open(atlas_path).convert("RGBA")

            tile_images = {}
            for tile_node in ts_root.findall("tile"):
                image_node = tile_node.find("image")
                if image_node is None:
                    continue
                image_path = (ts_path.parent / image_node.attrib["source"]).resolve()
                if image_path.exists():
                    tile_images[_read_int(tile_node.attrib, "id")] = Image.open(image_path).convert("RGBA")

            tilesets.append(
                {
                    "firstgid": firstgid,
                    "tile_width": tile_w,
                    "tile_height": tile_h,
                    "columns": columns,
                    "atlas": atlas,
                    "tile_images": tile_images,
                }
            )
        tilesets.sort(key=lambda item: item["firstgid"])
        return tilesets

    def _tileset_for_gid(self, gid):
        clean_gid = gid & GID_MASK
        chosen = None
        for tileset in self.tilesets:
            if clean_gid >= tileset["firstgid"]:
                chosen = tileset
            else:
                break
        return chosen

    def tile_image(self, gid: int):
        clean_gid = gid & GID_MASK
        if clean_gid <= 0:
            return None
        tileset = self._tileset_for_gid(clean_gid)
        if not tileset:
            return None
        local_id = clean_gid - tileset["firstgid"]
        if local_id in tileset["tile_images"]:
            return tileset["tile_images"][local_id].copy()
        atlas = tileset["atlas"]
        columns = tileset["columns"]
        if atlas is None or columns <= 0:
            return None
        tile_w = tileset["tile_width"]
        tile_h = tileset["tile_height"]
        sx = (local_id % columns) * tile_w
        sy = (local_id // columns) * tile_h
        return atlas.crop((sx, sy, sx + tile_w, sy + tile_h))


def _parse_csv_data(text: str) -> list[int]:
    return [int(part) for part in re.split(r"\s*,\s*", (text or "").strip()) if part.strip()]


def _selected(name: str, include_layers: set[str] | None, exclude_layers: set[str] | None):
    if include_layers is not None and name not in include_layers:
        return False
    if exclude_layers is not None and name in exclude_layers:
        return False
    return True


def _render_tile_layer(canvas: Image.Image, source: TmxTileSource, layer_node: ET.Element):
    data_node = layer_node.find("data")
    if data_node is None:
        return
    gids = _parse_csv_data(data_node.text or "")
    for idx, gid in enumerate(gids):
        if (gid & GID_MASK) <= 0:
            continue
        tile = source.tile_image(gid)
        if tile is None:
            continue
        if tile.size != (source.tile_width, source.tile_height):
            tile = tile.resize((source.tile_width, source.tile_height), _resample())
        x = (idx % source.map_width) * source.tile_width
        y = (idx // source.map_width) * source.tile_height
        canvas.alpha_composite(tile, (x, y))


def _render_object_layer(canvas: Image.Image, source: TmxTileSource, layer_node: ET.Element):
    for obj_node in layer_node.findall("object"):
        gid_raw = obj_node.attrib.get("gid")
        image = None
        if gid_raw:
            image = source.tile_image(int(gid_raw))
        else:
            image_node = obj_node.find("image")
            if image_node is not None:
                image_path = (source.tmx_path.parent / image_node.attrib["source"]).resolve()
                if image_path.exists():
                    image = Image.open(image_path).convert("RGBA")
        if image is None:
            continue
        x = float(obj_node.attrib.get("x", 0))
        y = float(obj_node.attrib.get("y", 0))
        w = float(obj_node.attrib.get("width", image.width))
        h = float(obj_node.attrib.get("height", image.height))
        scaled = image.resize((max(1, round(w)), max(1, round(h))), _resample())
        canvas.alpha_composite(scaled, (round(x), round(y)))


def render_tmx(
    tmx_path: str | Path,
    output_path: str | Path,
    include_layers: Iterable[str] | None = None,
    exclude_layers: Iterable[str] | None = None,
):
    source = TmxTileSource(Path(tmx_path))
    canvas = Image.new("RGBA", source.world_size, (0, 0, 0, 0))
    include = set(include_layers) if include_layers else None
    exclude = set(exclude_layers) if exclude_layers else None

    for node in source.map_root:
        layer_name = node.attrib.get("name", "")
        if not _selected(layer_name, include, exclude):
            continue
        if node.tag == "layer":
            _render_tile_layer(canvas, source, node)
        elif node.tag == "objectgroup":
            _render_object_layer(canvas, source, node)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return {
        "output_path": str(output_path),
        "world_size": list(source.world_size),
        "tile_size": [source.tile_width, source.tile_height],
        "map_size_tiles": [source.map_width, source.map_height],
    }

