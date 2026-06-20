from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def _chunk_id(col: int, row: int):
    return f"chunk_{col:02}_{row:02}"


def _neighbors(col: int, row: int, cols: int, rows: int):
    out = {}
    if row > 0:
        out["north"] = _chunk_id(col, row - 1)
    if row + 1 < rows:
        out["south"] = _chunk_id(col, row + 1)
    if col > 0:
        out["west"] = _chunk_id(col - 1, row)
    if col + 1 < cols:
        out["east"] = _chunk_id(col + 1, row)
    return out


def _resample_filter():
    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS", Image.BICUBIC)


def _resize_to_max(image: Image.Image, max_size):
    if not max_size:
        return image
    max_size = int(max_size)
    if max_size <= 0:
        return image
    scale = min(max_size / max(image.size), 1.0)
    if scale >= 1.0:
        return image
    size = (
        max(1, int(round(image.width * scale))),
        max(1, int(round(image.height * scale))),
    )
    return image.resize(size, _resample_filter())


def slice_chunks(image_path, output_dir, chunk_size, overlap, generation_max_size=None):
    image_path = Path(image_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    image = Image.open(image_path).convert("RGBA")
    chunk_w, chunk_h = [int(v) for v in chunk_size]
    overlap = max(0, int(overlap))
    if chunk_w <= 0 or chunk_h <= 0:
        raise ValueError("chunk_size values must be positive")

    width, height = image.size
    cols = max(1, math.ceil(width / chunk_w))
    rows = max(1, math.ceil(height / chunk_h))
    chunks = []

    for row in range(rows):
        for col in range(cols):
            chunk_id = _chunk_id(col, row)
            world_x = col * chunk_w
            world_y = row * chunk_h
            world_w = min(chunk_w, width - world_x)
            world_h = min(chunk_h, height - world_y)
            src_x = max(0, world_x - overlap)
            src_y = max(0, world_y - overlap)
            src_r = min(width, world_x + world_w + overlap)
            src_b = min(height, world_y + world_h + overlap)

            chunk_dir = output_dir / chunk_id
            chunk_dir.mkdir(parents=True, exist_ok=True)
            source_path = chunk_dir / "source.png"
            source = image.crop((src_x, src_y, src_r, src_b))
            source = _resize_to_max(source, generation_max_size)
            source.save(source_path)

            metadata = {
                "chunk_id": chunk_id,
                "grid": [col, row],
                "world_rect": [world_x, world_y, world_w, world_h],
                "source_rect_with_overlap": [src_x, src_y, src_r - src_x, src_b - src_y],
                "source_image_size": list(source.size),
                "generation_max_size": generation_max_size,
                "overlap": overlap,
                "source_image": str(source_path),
                "painted_image": str(chunk_dir / "painted.png"),
                "neighbors": _neighbors(col, row, cols, rows),
            }
            metadata_path = chunk_dir / "metadata.json"
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            chunks.append(metadata)

    manifest = {
        "source_image": str(image_path),
        "image_size": [width, height],
        "chunk_size": [chunk_w, chunk_h],
        "world_chunk_size": [chunk_w, chunk_h],
        "generation_max_size": generation_max_size,
        "overlap": overlap,
        "grid_size": [cols, rows],
        "chunks": chunks,
    }
    manifest_path = output_dir / "chunks_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest

