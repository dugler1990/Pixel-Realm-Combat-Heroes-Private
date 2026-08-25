"""Export PaintedGround from a TMX map as a uniform grid of PNG chunks."""

from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def _find_painted_ground(map_root: ET.Element):
    for node in map_root:
        if node.tag == "objectgroup" and node.attrib.get("name", "").lower() == "paintedground":
            objects = node.findall("object")
            if not objects:
                raise ValueError("PaintedGround layer has no objects")
            if len(objects) > 1:
                raise ValueError(
                    f"PaintedGround has {len(objects)} objects; export supports one background object"
                )
            return objects[0]
    raise ValueError("No PaintedGround object layer found")


def _resolve_image_path(map_path: Path, map_root: ET.Element, painted_obj: ET.Element):
    gid_raw = painted_obj.attrib.get("gid")
    if not gid_raw:
        raise ValueError("PaintedGround object has no gid")
    gid = int(gid_raw)

    # TMX rule: a gid belongs to the tileset with the LARGEST firstgid <= gid (each range is
    # capped by the next tileset's firstgid), so an overlapping declared tilecount in an
    # earlier tileset must not shadow a later one.
    tileset_nodes = [n for n in map_root if n.tag == "tileset"]
    chosen_ts = None
    chosen_firstgid = None
    for ts in tileset_nodes:
        source = ts.attrib.get("source")
        if not source:
            continue
        firstgid = int(ts.attrib["firstgid"])
        if firstgid <= gid and (chosen_firstgid is None or firstgid > chosen_firstgid):
            chosen_firstgid = firstgid
            chosen_ts = (map_path.parent / source).resolve()
    if chosen_ts is None:
        raise ValueError(f"Could not resolve tileset for gid {gid}")
    ts_root_data = ET.parse(chosen_ts).getroot()

    local_id = gid - chosen_firstgid
    tile_node = ts_root_data.find(f"./tile[@id='{local_id}']")
    if tile_node is None:
        tile_node = ts_root_data.find("./tile")
    if tile_node is None:
        raise ValueError("No tile image entry in painted tileset")

    image_node = tile_node.find("image")
    if image_node is None:
        raise ValueError("Painted tile has no image")
    image_path = (chosen_ts.parent / image_node.attrib["source"]).resolve()
    if not image_path.exists():
        raise ValueError(f"Painted image not found: {image_path}")
    return image_path


def export_painted_grid(
    map_path: Path,
    output_dir: Path,
    *,
    cols: int | None = 5,
    rows: int | None = 5,
    chunk_width: int | None = None,
    chunk_height: int | None = None,
    pad_to_chunk_size: bool = True,
) -> dict:
    map_path = Path(map_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    map_root = ET.parse(map_path).getroot()
    painted_obj = _find_painted_ground(map_root)
    image_path = _resolve_image_path(map_path, map_root, painted_obj)

    target_w = int(round(float(painted_obj.attrib["width"])))
    target_h = int(round(float(painted_obj.attrib["height"])))
    origin_x = float(painted_obj.attrib.get("x", "0"))
    origin_y = float(painted_obj.attrib.get("y", "0"))

    resampling = getattr(Image, "Resampling", Image)
    filter_fast = getattr(resampling, "BILINEAR", Image.BILINEAR)

    if chunk_width and chunk_height:
        chunk_w = int(chunk_width)
        chunk_h = int(chunk_height)
        if cols is None:
            cols = max(1, math.ceil(target_w / chunk_w))
        if rows is None:
            rows = max(1, math.ceil(target_h / chunk_h))
    else:
        if cols is None or rows is None:
            raise ValueError("Provide --cols and --rows, or --chunk-width and --chunk-height")
        chunk_w = math.ceil(target_w / cols)
        chunk_h = math.ceil(target_h / rows)
    chunks = []
    grid_origin_top_y = int(round(origin_y - target_h))
    grid_origin_x = int(round(origin_x))

    with Image.open(image_path) as src:
        src = src.convert("RGBA")
        src_w, src_h = src.size

        for row in range(rows):
            for col in range(cols):
                src_left = int(math.floor(col * src_w / cols))
                src_top = int(math.floor(row * src_h / rows))
                src_right = int(math.ceil((col + 1) * src_w / cols))
                src_bottom = int(math.ceil((row + 1) * src_h / rows))

                out_left = col * chunk_w
                out_top = row * chunk_h
                out_right = min(target_w, out_left + chunk_w)
                out_bottom = min(target_h, out_top + chunk_h)
                content_w = out_right - out_left
                content_h = out_bottom - out_top

                crop = src.crop((src_left, src_top, src_right, src_bottom))
                crop = crop.resize((content_w, content_h), filter_fast)

                if pad_to_chunk_size and chunk_width and chunk_height:
                    tile = Image.new("RGB", (chunk_w, chunk_h), color=(0, 0, 0))
                    tile.paste(crop.convert("RGB"), (0, 0))
                    padded = content_w < chunk_w or content_h < chunk_h
                    out_w, out_h = chunk_w, chunk_h
                else:
                    tile = crop
                    padded = False
                    out_w, out_h = content_w, content_h

                chunk_id = f"chunk_{col:02}_{row:02}"
                out_path = output_dir / f"{chunk_id}.png"
                tile.save(out_path)
                chunks.append(
                    {
                        "chunk_id": chunk_id,
                        "grid": [col, row],
                        "file": str(out_path),
                        "painted_image": str(out_path),
                        "source_pixel_rect": [src_left, src_top, src_right - src_left, src_bottom - src_top],
                        "content_rect": [0, 0, content_w, content_h],
                        "output_pixel_rect": [out_left, out_top, out_w, out_h],
                        "padded": padded,
                        "world_rect": [
                            grid_origin_x + col * chunk_w,
                            grid_origin_top_y + row * chunk_h,
                            chunk_w if pad_to_chunk_size and chunk_width else out_w,
                            chunk_h if pad_to_chunk_size and chunk_height else out_h,
                        ],
                    }
                )

    manifest = {
        "map_tmx": str(map_path),
        "source_image": str(image_path),
        "source_image_size": [src_w, src_h],
        "paintedground_object": {
            "x": origin_x,
            "y": origin_y,
            "width": target_w,
            "height": target_h,
        },
        "grid_origin": [grid_origin_x, grid_origin_top_y],
        "grid_world_size": [cols * chunk_w, rows * chunk_h],
        "grid_size": [cols, rows],
        "chunk_size_px": [chunk_w, chunk_h],
        "pad_to_chunk_size": pad_to_chunk_size,
        "leonardo_4k_pair": [5056, 3392] if chunk_w == 5056 and chunk_h == 3392 else None,
        "chunks": chunks,
    }
    manifest_path = output_dir / "grid_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export PaintedGround as a PNG grid.")
    parser.add_argument(
        "--map",
        default="levels/Frostreach/expanse/map.tmx",
        help="Path to map.tmx",
    )
    parser.add_argument(
        "--output",
        default="levels/Frostreach/expanse/export/painted_4k",
        help="Output directory for PNG chunks",
    )
    parser.add_argument("--cols", type=int, default=None, help="Grid columns (optional with --chunk-width)")
    parser.add_argument("--rows", type=int, default=None, help="Grid rows (optional with --chunk-height)")
    parser.add_argument(
        "--chunk-width",
        type=int,
        default=5056,
        help="Fixed chunk width in px (Nano Banana 2 4K 3:2 width). Grid cols computed if --cols omitted.",
    )
    parser.add_argument(
        "--chunk-height",
        type=int,
        default=3392,
        help="Fixed chunk height in px (Nano Banana 2 4K 3:2 height). Grid rows computed if --rows omitted.",
    )
    parser.add_argument(
        "--no-pad-to-chunk-size",
        action="store_true",
        help="Disable black padding for partial edge cells (legacy behavior).",
    )
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parent
    repo_root = base.parents[1]

    def _resolve(raw: str) -> Path:
        path = Path(raw)
        return path if path.is_absolute() else (repo_root / path).resolve()

    chunk_width = args.chunk_width if args.chunk_width > 0 else None
    chunk_height = args.chunk_height if args.chunk_height > 0 else None
    result = export_painted_grid(
        _resolve(args.map),
        _resolve(args.output),
        cols=args.cols,
        rows=args.rows,
        chunk_width=chunk_width,
        chunk_height=chunk_height,
        pad_to_chunk_size=not args.no_pad_to_chunk_size,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
