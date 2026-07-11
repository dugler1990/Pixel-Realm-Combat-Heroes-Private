"""Tests for the containment cull (drop obstacles fully inside a larger one)."""

from __future__ import annotations

from tools.painted_map_pipeline.collision.sam3.containment_cull import (
    ContainmentCullConfig,
    filter_contained_polygons,
)


def _rect(x: int, y: int, w: int, h: int) -> list[list[float]]:
    return [
        [float(x), float(y)],
        [float(x + w), float(y)],
        [float(x + w), float(y + h)],
        [float(x), float(y + h)],
    ]


def _poly(cls: str, x: int, y: int, w: int, h: int, *, canopy: bool = False) -> dict:
    return {
        "class": cls,
        "sam3_class": cls,
        "points": _rect(x, y, w, h),
        "collision_mode": "canopy" if canopy else "solid",
    }


CANVAS = (512, 512)
CFG = ContainmentCullConfig(containment_threshold=0.99, analysis_stride=1)


def test_small_inside_large_dropped():
    polys = [_poly("mountain", 100, 100, 300, 300), _poly("rock", 150, 150, 40, 40)]
    survivors, stats = filter_contained_polygons(polys, image_size=CANVAS, config=CFG)
    assert [p["sam3_class"] for p in survivors] == ["mountain"]
    assert stats["dropped"] == 1


def test_partial_overlap_kept():
    polys = [_poly("rock", 100, 100, 200, 200), _poly("rock", 250, 150, 200, 200)]
    survivors, stats = filter_contained_polygons(polys, image_size=CANVAS, config=CFG)
    assert len(survivors) == 2
    assert stats["dropped"] == 0


def test_exact_duplicate_deduped():
    polys = [_poly("rock", 100, 100, 100, 100), _poly("rock", 100, 100, 100, 100)]
    survivors, stats = filter_contained_polygons(polys, image_size=CANVAS, config=CFG)
    assert len(survivors) == 1
    assert stats["dropped"] == 1


def test_largest_kept_nested_dropped():
    polys = [
        _poly("rock", 200, 200, 20, 20),
        _poly("mountain", 100, 100, 300, 300),
        _poly("ruins", 150, 150, 60, 60),
    ]
    survivors, stats = filter_contained_polygons(polys, image_size=CANVAS, config=CFG)
    assert [p["sam3_class"] for p in survivors] == ["mountain"]
    assert stats["dropped"] == 2


def test_canopy_inside_solid_never_dropped():
    # A tree fully inside a solid is still kept (canopy is not a cull candidate).
    polys = [_poly("mountain", 100, 100, 300, 300), _poly("tree", 150, 150, 40, 40, canopy=True)]
    survivors, stats = filter_contained_polygons(polys, image_size=CANVAS, config=CFG)
    assert len(survivors) == 2
    assert stats["dropped"] == 0


def test_canopy_is_not_a_container():
    # A solid inside a tree canopy is real collision and must be kept (canopy does
    # not block, so it never covers anything).
    polys = [_poly("tree", 100, 100, 300, 300, canopy=True), _poly("rock", 150, 150, 40, 40)]
    survivors, stats = filter_contained_polygons(polys, image_size=CANVAS, config=CFG)
    assert len(survivors) == 2
    assert stats["dropped"] == 0
