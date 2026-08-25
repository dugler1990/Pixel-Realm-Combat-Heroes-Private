"""Stitch the accepted levels back into one world-sized image.

The pipeline generates and accepts levels one at a time, which leaves no way to look at the
result as a whole -- and the whole is the only place the things that matter show up: whether
the joins read, whether the scale is right, whether the padding chain survives across a dozen
levels. This is the step between accepted art and ``bootstrap_from_png``, which turns a single
background PNG into a playable TMX.

Cores only, never generation regions. Generation regions overlap by the padding buffer on
every interior edge, so pasting them would make the result depend on the order levels happened
to be accepted in. Core polygons tile the landmass exactly and never overlap, so every world
pixel has exactly one owner and the stitch is unambiguous.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .config import load_config
from .masks import rasterize_polygon
from .models import LevelState
from .package_builder import level_paths
from .state_store import read_json

Image.MAX_IMAGE_PIXELS = None


def _placement(manifest: dict[str, Any]) -> tuple[int, int]:
    """Where this level's canvas sits in the world, in world pixels.

    A canvas pixel is offset from its crop by ``canvas_offset`` (the crop is centred on a
    canvas that is usually a little larger), and the crop sits at ``scaled_crop_origin``. So
    the canvas origin in world space is one minus the other.
    """
    transform = manifest["transform"]
    origin_x, origin_y = transform["scaled_crop_origin"]
    offset_x, offset_y = transform["canvas_offset"]
    return origin_x - offset_x, origin_y - offset_y


def assemble_world(root: str | Path, *, fallback: bool = True) -> tuple[Image.Image, dict]:
    """The accepted art laid back onto the world map it was cut from.

    ``fallback`` starts from the source map, so ground from levels not yet generated is the
    soft upscale rather than a hole -- the map stays walkable while a run is half finished, and
    unfinished ground is obvious on sight. Without it the background is black.
    """
    root_path = Path(root).resolve()
    config = load_config(root_path / "config.resolved.json")
    run = read_json(root_path / "run.json")

    with Image.open(config.world_map) as opened:
        source = opened.convert("RGB")
    world = source.copy() if fallback else Image.new("RGB", source.size, (0, 0, 0))

    # Acceptance order, so that if two cores ever did touch, the later acceptance wins -- the
    # same rule the padding chain uses. They should not touch; this only decides ties.
    accepted: list[tuple[int, str, dict]] = []
    for level_id, entry in run["levels"].items():
        if entry.get("state") != LevelState.ACCEPTED.value:
            continue
        manifest = read_json(level_paths(root_path, level_id)["manifest"])
        accepted.append((int(manifest.get("acceptance_index", 0)), level_id, manifest))
    accepted.sort()

    placed: list[str] = []
    for _, level_id, manifest in accepted:
        image_path = Path(manifest["accepted_image"])
        if not image_path.is_file():
            continue
        with Image.open(image_path) as opened:
            art = opened.convert("RGB")

        left, top = _placement(manifest)
        # The core in this canvas's own coordinates, so the cut is a plain composite.
        core = tuple((x - left, y - top) for x, y in
                     (tuple(point) for point in manifest["core_polygon_world"]))
        mask = rasterize_polygon(art.size, core)
        world.paste(art, (left, top), mask)
        placed.append(level_id)

    total = len(run["levels"])
    return world, {
        "world_size": list(source.size),
        "levels_total": total,
        "levels_placed": len(placed),
        "placed": sorted(placed),
        "missing": sorted(set(run["levels"]) - set(placed)),
        "fallback": fallback,
    }


def core_coverage(root: str | Path) -> dict:
    """How much of the landmass the accepted cores account for, and whether any overlap.

    Cores tiling exactly is the assumption the whole stitch rests on, so it is worth being
    able to check rather than assume.
    """
    root_path = Path(root).resolve()
    config = load_config(root_path / "config.resolved.json")
    run = read_json(root_path / "run.json")
    with Image.open(config.world_map) as opened:
        width, height = opened.size

    counts = np.zeros((height, width), dtype=np.uint8)
    for level_id, entry in run["levels"].items():
        if entry.get("state") != LevelState.ACCEPTED.value:
            continue
        manifest = read_json(level_paths(root_path, level_id)["manifest"])
        left, top = _placement(manifest)
        canvas_w, canvas_h = manifest["canvas_size"]
        core = tuple((x - left, y - top) for x, y in
                     (tuple(point) for point in manifest["core_polygon_world"]))
        piece = np.asarray(rasterize_polygon((canvas_w, canvas_h), core)) > 0
        # Clip to the world: a canvas can hang off the edge of the map.
        x0, y0 = max(0, left), max(0, top)
        x1, y1 = min(width, left + canvas_w), min(height, top + canvas_h)
        counts[y0:y1, x0:x1] += piece[y0 - top : y1 - top, x0 - left : x1 - left]

    return {
        "covered_px": int((counts > 0).sum()),
        "overlapping_px": int((counts > 1).sum()),
        "world_px": int(width * height),
    }
