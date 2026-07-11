"""Per-category drop / confidence filter for SAM3 polygons at merge time.

Some SAM3 prompts are unreliable on this art style. On Frostreach expanse the
"cliff" prompt never resolves a real object - it returns near-tile-sized masks at
0.10-0.28 confidence (max observed 0.605, and even those are specks), so there is
no confidence threshold that separates good cliffs from bad. This filter lets a
whole class be dropped outright, a per-class confidence floor be applied to the
classes worth keeping, and a max-area cap drop whole-tile frame-filler blobs (SAM3
also emits ~tile-sized masks for ruins/mountain at 0.12-0.31 confidence).

Distinct from the speck cull ([`isolation_cull.py`](isolation_cull.py)): that one
removes small fragments by size x openness; this one removes whole classes,
low-confidence detections, and oversized blobs before the speck cull runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .polygon_filters import CANOPY_CLASSES


@dataclass
class ClassFilterConfig:
    # Classes removed entirely, regardless of confidence or size.
    drop_classes: frozenset[str] = field(default_factory=frozenset)
    # Per-class confidence floor: a polygon of this class is dropped when its
    # confidence is below the value. Classes absent here are not confidence-gated.
    min_confidence: dict[str, float] = field(default_factory=dict)
    # Drop any polygon whose area exceeds this many map px^2 (whole-tile SAM3
    # frame-fillers). None disables the size cap.
    max_area: float | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "ClassFilterConfig":
        if not data:
            return cls()
        drop = data.get("drop_classes") or []
        conf = data.get("min_confidence") or {}
        max_area = data.get("max_area")
        return cls(
            drop_classes=frozenset(str(c).strip().lower() for c in drop),
            min_confidence={str(k).strip().lower(): float(v) for k, v in conf.items()},
            max_area=float(max_area) if max_area is not None else None,
        )

    def is_active(self) -> bool:
        return bool(self.drop_classes or self.min_confidence or self.max_area is not None)


def _class_of(poly: dict[str, Any]) -> str:
    return str(poly.get("sam3_class") or poly.get("class") or "").strip().lower()


def _is_canopy(poly: dict[str, Any]) -> bool:
    if str(poly.get("collision_mode") or "").strip().lower() == "canopy":
        return True
    return _class_of(poly) in CANOPY_CLASSES


def _area(poly: dict[str, Any]) -> float:
    pts = poly.get("points") or []
    n = len(pts)
    if n < 3:
        return 0.0
    acc = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return abs(acc) / 2.0


def filter_polygons_by_class(
    polygons: list[dict[str, Any]],
    config: ClassFilterConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Drop whole classes and below-floor-confidence polygons.

    Returns ``(survivors, stats)``. ``stats['dropped_by_class']`` maps class name
    to how many polygons that class lost.
    """
    cfg = config or ClassFilterConfig()
    stats: dict[str, Any] = {
        "input": len(polygons),
        "kept": 0,
        "dropped": 0,
        "dropped_by_class": {},
    }
    if not cfg.is_active() or not polygons:
        stats["kept"] = len(polygons)
        return list(polygons), stats

    survivors: list[dict[str, Any]] = []
    by_class: dict[str, int] = {}
    dropped_oversize = 0
    for poly in polygons:
        cls = _class_of(poly)
        drop = False
        oversize = False
        if cls in cfg.drop_classes:
            drop = True
        elif cfg.max_area is not None and not _is_canopy(poly) and _area(poly) > cfg.max_area:
            # Canopy (trees) is walk-under, not collision -> never size-capped.
            drop = True
            oversize = True
        else:
            floor = cfg.min_confidence.get(cls)
            if floor is not None and float(poly.get("confidence") or 0.0) < floor:
                drop = True
        if drop:
            by_class[cls] = by_class.get(cls, 0) + 1
            stats["dropped"] += 1
            if oversize:
                dropped_oversize += 1
            continue
        survivors.append(poly)

    stats["kept"] = len(survivors)
    stats["dropped_by_class"] = by_class
    stats["dropped_oversize"] = dropped_oversize
    return survivors, stats
