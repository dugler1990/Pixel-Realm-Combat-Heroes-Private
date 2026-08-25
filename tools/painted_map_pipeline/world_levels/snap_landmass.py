"""Trim a painted world map so its landmass is exactly an N-gon.

A prep step between ``bootstrap_from_png`` and ``make_grid_plan``. See GRID_PLAN_NOTES.md.

Why it exists: ``make_grid_plan`` has to give every level a core polygon and a generation
polygon, and ``prepare`` rejects the pair unless the core is fully inside the generation. When
both are traced from a ragged pixel coastline and simplified separately, they disagree about
where that coast is by a pixel or two and the check fails. If the coastline is genuinely a
polygon of straight edges, both become exact clips of the same shape and containment is
guaranteed by construction -- no tracing, no tolerance, nothing to drift.

The polygon is INSCRIBED: it only ever cuts land away, never claims black as land, because the
image has to keep matching the coordinates. Measured on the 7x6 sunspine map, ten vertices
costs 0.57% of the land -- a 16px trim.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

DEFAULT_MAX_VERTICES = 10
DEFAULT_LAND_THRESHOLD = 40
# The coast is found on a downscaled copy: 276 MP of contour tracing buys nothing, the shape is
# thousands of pixels across, and the inset is verified at full resolution afterwards anyway.
WORK_DIVISOR = 8


def _filled_land(mask: np.ndarray) -> np.ndarray:
    """Land with interior holes closed.

    Dark pixels inside the landmass -- shadow, water -- fall under the threshold and read as
    background. Left unfilled they make an inscribed polygon impossible: every candidate
    "covers black" somewhere in the middle, which is what made an earlier attempt report that
    no polygon of any size fits.
    """
    inverted = (~mask).astype(np.uint8)
    flooded = inverted.copy()
    cv2.floodFill(flooded, np.zeros((mask.shape[0] + 2, mask.shape[1] + 2), np.uint8), (0, 0), 0)
    return mask | flooded.astype(bool)


def _offset(polygon: list[tuple[float, float]], distance: float) -> list[tuple[float, float]]:
    """Move every edge inward by ``distance`` and re-intersect. Vertex count is unchanged."""
    n = len(polygon)
    twice_area = sum(
        polygon[i][0] * polygon[(i + 1) % n][1] - polygon[(i + 1) % n][0] * polygon[i][1]
        for i in range(n)
    )
    sign = 1.0 if twice_area > 0 else -1.0
    lines = []
    for i in range(n):
        (x1, y1), (x2, y2) = polygon[i], polygon[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy) or 1.0
        lines.append((x1 - sign * dy / length * distance, y1 + sign * dx / length * distance, dx, dy))
    out = []
    for i in range(n):
        ax, ay, adx, ady = lines[i - 1]
        bx, by, bdx, bdy = lines[i]
        denominator = adx * bdy - ady * bdx
        if abs(denominator) < 1e-9:
            out.append((bx, by))
            continue
        t = ((bx - ax) * bdy - (by - ay) * bdx) / denominator
        out.append((ax + adx * t, ay + ady * t))
    return out


def find_polygon(land: np.ndarray, max_vertices: int) -> tuple[list[tuple[float, float]], int]:
    """The largest inscribed polygon of at most ``max_vertices`` edges, and its inset."""
    contours, _ = cv2.findContours(
        land.astype(np.uint8) * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    contour = max(contours, key=cv2.contourArea)
    perimeter = cv2.arcLength(contour, True)

    best: tuple[int, list, int] | None = None
    for fraction in (0.0005, 0.001, 0.002, 0.003, 0.004, 0.006, 0.010, 0.015, 0.020, 0.030):
        approx = cv2.approxPolyDP(contour, fraction * perimeter, True).reshape(-1, 2)
        if len(approx) > max_vertices or len(approx) < 3:
            continue
        for inset in range(0, 200):
            candidate = _offset([tuple(map(float, p)) for p in approx], inset)
            filled = np.zeros(land.shape, np.uint8)
            cv2.fillPoly(filled, [np.round(candidate).astype(np.int32)], 1)
            covered = filled.astype(bool)
            if (covered & ~land).any():
                continue
            kept = int((covered & land).sum())
            # More vertices is not reliably better -- approxPolyDP can place one badly, and on
            # this map 8 vertices needs a 200px inset while 10 needs 16. So keep whichever
            # actually retains the most land.
            if best is None or kept > best[0]:
                best = (kept, candidate, inset)
            break
    if best is None:
        raise ValueError(f"no inscribed polygon of {max_vertices} or fewer vertices was found")
    return best[1], best[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("world_map")
    parser.add_argument("--out", required=True, help="Trimmed map PNG.")
    parser.add_argument("--polygon-out", default=None, help="Write the polygon as JSON here.")
    parser.add_argument("--overlay", default=None, help="Review image: the polygon on the map.")
    parser.add_argument("--max-vertices", type=int, default=DEFAULT_MAX_VERTICES)
    parser.add_argument("--land-threshold", type=int, default=DEFAULT_LAND_THRESHOLD)
    args = parser.parse_args()

    with Image.open(args.world_map) as opened:
        full = opened.convert("RGB")
    width, height = full.size
    small = np.asarray(
        full.resize((width // WORK_DIVISOR, height // WORK_DIVISOR), Image.LANCZOS)
    ).sum(axis=2) > args.land_threshold
    land_small = _filled_land(small)

    polygon_small, inset = find_polygon(land_small, args.max_vertices)
    polygon = [(x * WORK_DIVISOR, y * WORK_DIVISOR) for x, y in polygon_small]

    # Verify at full resolution and pull in further if the downscale flattered us.
    pixels = np.asarray(full)
    land_full = _filled_land(pixels.sum(axis=2) > args.land_threshold)
    extra = 0
    while True:
        candidate = _offset(polygon, extra)
        mask = np.zeros(land_full.shape, np.uint8)
        cv2.fillPoly(mask, [np.round(candidate).astype(np.int32)], 1)
        inside = mask.astype(bool)
        if not (inside & ~land_full).any() or extra > 400:
            break
        extra += 8
    polygon = [(int(round(x)), int(round(y))) for x, y in candidate]

    before = int(land_full.sum())
    after = int((inside & land_full).sum())
    trimmed = np.where(inside[..., None], pixels, 0).astype(np.uint8)
    Image.fromarray(trimmed).save(args.out)

    print(f"landmass snapped to {len(polygon)} vertices")
    print(f"  inset {inset * WORK_DIVISOR}px (+{extra} at full res)")
    print(f"  land {before:,} -> {after:,}  ({100 * (before - after) / before:.2f}% trimmed)")
    print(f"  {args.out}")

    if args.polygon_out:
        Path(args.polygon_out).write_text(json.dumps({"polygon": polygon}, indent=2) + "\n")
        print(f"  {args.polygon_out}")
    if args.overlay:
        from PIL import ImageDraw

        scale = 1400 / width
        view = Image.fromarray(trimmed).resize((1400, round(height * scale)), Image.LANCZOS)
        draw = ImageDraw.Draw(view, "RGBA")
        draw.polygon([(x * scale, y * scale) for x, y in polygon],
                     outline=(255, 60, 60, 255), width=3)
        for x, y in polygon:
            draw.ellipse([x * scale - 5, y * scale - 5, x * scale + 5, y * scale + 5],
                         fill=(255, 220, 60, 255))
        view.save(args.overlay)
        print(f"  {args.overlay}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
