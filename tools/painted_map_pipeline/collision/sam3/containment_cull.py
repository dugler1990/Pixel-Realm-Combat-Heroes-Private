"""Containment cull for SAM3 obstacles at merge time.

Drops solid polygons that sit fully inside a larger solid obstacle: their
collision is redundant (the larger shape already blocks that ground), so removing
them lightens the map without changing what the player can walk on.

Greedy, largest-first: keep a running union of the shapes already kept, and drop a
polygon only when it is (>= threshold) already covered by that union. Because we
process largest-first, a shape is dropped only when *larger shapes that remain*
cover it, so ``union(kept) == union(all)`` within the threshold - collision is
preserved by construction. Canopy (trees) is never removed and never acts as a
container, since it does not block movement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .polygon_filters import CANOPY_CLASSES


@dataclass
class ContainmentCullConfig:
    # Fraction of a polygon's pixels that must already be covered by larger kept
    # shapes for it to count as redundant. <1.0 tolerates rasterization error.
    containment_threshold: float = 0.99
    # Rasterization downsample factor (speed vs precision).
    analysis_stride: int = 4

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "ContainmentCullConfig":
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in data.items() if key in known})


def _is_canopy(poly: dict[str, Any]) -> bool:
    if str(poly.get("collision_mode") or "").strip().lower() == "canopy":
        return True
    cls = str(poly.get("sam3_class") or poly.get("class") or "").strip().lower()
    return cls in CANOPY_CLASSES


def _area(points: list[list[float]]) -> float:
    n = len(points)
    if n < 3:
        return 0.0
    acc = 0.0
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return abs(acc) / 2.0


def _scaled(points: list[list[float]], stride: int) -> np.ndarray | None:
    if len(points) < 3:
        return None
    s = float(stride)
    arr = np.array([[int(round(x / s)), int(round(y / s))] for x, y in points], dtype=np.int32)
    return arr.reshape((-1, 1, 2))


def filter_contained_polygons(
    polygons: list[dict[str, Any]],
    *,
    image_size: tuple[int, int],
    config: ContainmentCullConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Drop solid polygons fully contained in a larger kept solid.

    Returns ``(survivors, stats)`` with stats ``{input, kept, dropped}``.
    """
    cfg = config or ContainmentCullConfig()
    width, height = int(image_size[0]), int(image_size[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid image_size: {image_size!r}")

    stride = max(1, int(cfg.analysis_stride))
    aw = max(1, int(math.ceil(width / stride)))
    ah = max(1, int(math.ceil(height / stride)))
    threshold = float(cfg.containment_threshold)

    stats: dict[str, Any] = {"input": len(polygons), "kept": 0, "dropped": 0}
    if not polygons:
        return [], stats

    # Solid candidates only: (area, polygon index, scaled points). Canopy is skipped
    # entirely (never dropped, never a container).
    solids: list[tuple[float, int, np.ndarray]] = []
    for idx, poly in enumerate(polygons):
        if _is_canopy(poly):
            continue
        sp = _scaled(poly.get("points") or [], stride)
        if sp is None:
            continue
        solids.append((_area(poly.get("points") or []), idx, sp))

    if not solids:
        stats["kept"] = len(polygons)
        return list(polygons), stats

    solids.sort(key=lambda t: t[0], reverse=True)

    kept_union = np.zeros((ah, aw), dtype=np.uint8)
    temp = np.zeros((ah, aw), dtype=np.uint8)
    drop: set[int] = set()

    for _area_val, idx, sp in solids:
        temp[:] = 0
        cv2.fillPoly(temp, [sp], 1)
        pixels = int(temp.sum())
        if pixels == 0:
            # Sub-cell polygon: redundant only if its location is already covered.
            pix = sp.reshape(-1, 2)
            cx = int(min(max(round(float(pix[:, 0].mean())), 0), aw - 1))
            cy = int(min(max(round(float(pix[:, 1].mean())), 0), ah - 1))
            if kept_union[cy, cx]:
                drop.add(idx)
            continue
        covered = int(cv2.bitwise_and(temp, kept_union).sum())
        if covered / pixels >= threshold:
            drop.add(idx)
        else:
            kept_union |= temp

    survivors = [poly for i, poly in enumerate(polygons) if i not in drop]
    stats["dropped"] = len(drop)
    stats["kept"] = len(survivors)
    return survivors, stats
