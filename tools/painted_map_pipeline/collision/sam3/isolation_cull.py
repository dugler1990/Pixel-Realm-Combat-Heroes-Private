"""Size x openness speck cull for SAM3 obstacles at merge time.

Replaces the original "isolation" cull, which could not fire on dense maps:
connected-componenting the *solid union* at 80-98% coverage welds each chunk
into one ~17M-px blob, so nothing ever reads as small or isolated.

Instead we component each solid class on its own (a lone fragment is a small
blob; a fragment touching its big parent fuses in and survives) and drop a blob
when its area falls under a size threshold that RISES with local openness:

    required = floor_area + openness**k * (ceiling_area - floor_area)
    drop blob if blob_area < required

So tiny blobs die everywhere, larger blobs die only where the surroundings are
open. Trees (canopy / walk-under) are never candidates. The cull runs across all
solid classes (cliff/mountain/rock/ruins/...), because on Frostreach expanse the
shatter specks are mostly cliff/mountain fragments, not rocks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from .polygon_filters import CANOPY_CLASSES


@dataclass
class SpeckCullConfig:
    # Blob below this many map px^2 is dropped regardless of openness ("tiny everywhere").
    floor_area: int = 150
    # At full openness, blobs below this many px^2 are dropped (ceiling of the curve).
    ceiling_area: int = 600
    # Curve steepness: required = floor + openness**k * (ceiling - floor).
    k: float = 1.0
    # Openness neighborhood radius in map px.
    radius: int = 350
    # Rasterization downsample factor for the openness field + blob grouping.
    analysis_stride: int = 2

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "SpeckCullConfig":
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{key: value for key, value in data.items() if key in known})


def _shoelace(points: list[list[float]]) -> float:
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


def _is_canopy(poly: dict[str, Any]) -> bool:
    if str(poly.get("collision_mode") or "").strip().lower() == "canopy":
        return True
    cls = str(poly.get("sam3_class") or poly.get("class") or "").strip().lower()
    return cls in CANOPY_CLASSES


def _class_of(poly: dict[str, Any]) -> str:
    return str(poly.get("sam3_class") or poly.get("class") or "").strip().lower()


def filter_specks_by_size_openness(
    polygons: list[dict[str, Any]],
    *,
    image_size: tuple[int, int],
    config: SpeckCullConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Drop small solid blobs whose size falls under the openness-scaled curve.

    Returns ``(survivors, stats)``. Canopy (trees) are never candidates and are
    always preserved; a solid blob is dropped (all its member polygons) only when
    its summed area is below ``floor + openness**k * (ceiling - floor)``.
    """
    cfg = config or SpeckCullConfig()
    width, height = int(image_size[0]), int(image_size[1])
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid image_size: {image_size!r}")

    stride = max(1, int(cfg.analysis_stride))
    aw = max(1, int(math.ceil(width / stride)))
    ah = max(1, int(math.ceil(height / stride)))

    stats: dict[str, Any] = {
        "input": len(polygons),
        "kept": 0,
        "dropped": 0,
        "blobs_total": 0,
        "blobs_dropped": 0,
    }
    if not polygons:
        return [], stats

    n_poly = len(polygons)
    areas = [0.0] * n_poly
    spts: list[np.ndarray | None] = [None] * n_poly
    solid_mask = np.zeros((ah, aw), dtype=np.uint8)
    idx_by_class: dict[str, list[int]] = {}

    for i, poly in enumerate(polygons):
        pts = poly.get("points") or []
        areas[i] = _shoelace(pts)
        sp = _scaled(pts, stride)
        spts[i] = sp
        if sp is None or _is_canopy(poly):
            continue
        cv2.fillPoly(solid_mask, [sp], 1)
        idx_by_class.setdefault(_class_of(poly), []).append(i)

    if not idx_by_class:
        stats["kept"] = len(polygons)
        return list(polygons), stats

    # Openness field: 1 - local solid coverage fraction, one O(N) box-filter pass.
    ks = 2 * max(1, int(round(cfg.radius / stride))) + 1
    cov = cv2.boxFilter(
        solid_mask.astype(np.float32), -1, (ks, ks), normalize=True, borderType=cv2.BORDER_REFLECT
    )
    openf = 1.0 - cov

    floor_a = float(cfg.floor_area)
    ceil_a = float(max(cfg.ceiling_area, cfg.floor_area))
    span = ceil_a - floor_a
    k = float(cfg.k)

    def required_for(openness: float) -> float:
        return floor_a + (openness ** k) * span

    drop: set[int] = set()
    blobs_total = 0
    blobs_dropped = 0

    for idxs in idx_by_class.values():
        # Per-class connected components: fragments of the same class fuse; a lone
        # fragment is its own small blob, a fragment touching its parent is absorbed.
        label = np.zeros((ah, aw), dtype=np.int32)
        for i in idxs:
            cv2.fillPoly(label, [spts[i]], i + 1)
        n_lab, cc = cv2.connectedComponents((label > 0).astype(np.uint8))

        present: set[int] = set()
        for cid in range(1, n_lab):
            mask = cc == cid
            members = [int(pl) - 1 for pl in np.unique(label[mask]) if pl > 0]
            if not members:
                continue
            blobs_total += 1
            present.update(members)
            area = sum(areas[i] for i in members)
            openness = float(openf[mask].mean())
            if area < required_for(openness):
                blobs_dropped += 1
                drop.update(members)

        # Sub-cell singletons: solid polys too small to rasterize at this stride.
        for i in idxs:
            if i in present:
                continue
            blobs_total += 1
            pix = spts[i].reshape(-1, 2)
            cx = int(min(max(round(float(pix[:, 0].mean())), 0), aw - 1))
            cy = int(min(max(round(float(pix[:, 1].mean())), 0), ah - 1))
            openness = float(openf[cy, cx])
            if areas[i] < required_for(openness):
                blobs_dropped += 1
                drop.add(i)

    survivors: list[dict[str, Any]] = []
    for i, poly in enumerate(polygons):
        if i in drop:
            stats["dropped"] += 1
            continue
        survivors.append(poly)

    stats["kept"] = len(survivors)
    stats["blobs_total"] = blobs_total
    stats["blobs_dropped"] = blobs_dropped
    return survivors, stats
