"""Tests for the per-category SAM3 class filter."""

from __future__ import annotations

from tools.painted_map_pipeline.collision.sam3.class_filters import (
    ClassFilterConfig,
    filter_polygons_by_class,
)


def _poly(cls: str, conf: float) -> dict:
    return {"sam3_class": cls, "class": cls, "confidence": conf}


def _poly_area(cls: str, side: int) -> dict:
    return {
        "sam3_class": cls,
        "class": cls,
        "confidence": 0.5,
        "points": [[0.0, 0.0], [float(side), 0.0], [float(side), float(side)], [0.0, float(side)]],
    }


def test_inactive_filter_keeps_everything():
    polys = [_poly("cliff", 0.1), _poly("rock", 0.5)]
    survivors, stats = filter_polygons_by_class(polys, ClassFilterConfig())
    assert len(survivors) == 2
    assert stats["dropped"] == 0


def test_drop_class_removes_entire_class():
    polys = [_poly("cliff", 0.6), _poly("cliff", 0.1), _poly("rock", 0.1)]
    cfg = ClassFilterConfig.from_mapping({"drop_classes": ["cliff"]})
    survivors, stats = filter_polygons_by_class(polys, cfg)
    assert [p["sam3_class"] for p in survivors] == ["rock"]
    assert stats["dropped"] == 2
    assert stats["dropped_by_class"] == {"cliff": 2}


def test_min_confidence_floor_per_class():
    polys = [_poly("ruins", 0.1), _poly("ruins", 0.4), _poly("rock", 0.05)]
    cfg = ClassFilterConfig.from_mapping({"min_confidence": {"ruins": 0.3}})
    survivors, stats = filter_polygons_by_class(polys, cfg)
    # ruins@0.1 dropped, ruins@0.4 kept; rock not gated -> kept.
    kept = sorted((p["sam3_class"], p["confidence"]) for p in survivors)
    assert kept == [("rock", 0.05), ("ruins", 0.4)]
    assert stats["dropped_by_class"] == {"ruins": 1}


def test_max_area_drops_oversized():
    # 200x200 = 40000 px2 dropped; 50x50 = 2500 px2 kept.
    polys = [_poly_area("mountain", 200), _poly_area("rock", 50)]
    cfg = ClassFilterConfig.from_mapping({"max_area": 10000})
    survivors, stats = filter_polygons_by_class(polys, cfg)
    assert [p["sam3_class"] for p in survivors] == ["rock"]
    assert stats["dropped"] == 1
    assert stats["dropped_oversize"] == 1


def test_max_area_skips_canopy():
    # A big tree (200x200=40000) exceeds the cap but is canopy/walk-under -> kept.
    big_tree = _poly_area("tree", 200)
    big_tree["collision_mode"] = "canopy"
    polys = [big_tree, _poly_area("mountain", 200)]
    cfg = ClassFilterConfig.from_mapping({"max_area": 10000})
    survivors, stats = filter_polygons_by_class(polys, cfg)
    assert [p["sam3_class"] for p in survivors] == ["tree"]
    assert stats["dropped"] == 1


def test_drop_class_takes_precedence_over_confidence():
    polys = [_poly("cliff", 0.99)]
    cfg = ClassFilterConfig.from_mapping(
        {"drop_classes": ["cliff"], "min_confidence": {"cliff": 0.1}}
    )
    survivors, stats = filter_polygons_by_class(polys, cfg)
    assert survivors == []
    assert stats["dropped"] == 1
