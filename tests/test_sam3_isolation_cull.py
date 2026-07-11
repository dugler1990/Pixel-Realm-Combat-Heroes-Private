"""Tests for the size x openness SAM3 speck cull."""

from __future__ import annotations

from tools.painted_map_pipeline.collision.sam3.isolation_cull import (
    SpeckCullConfig,
    filter_specks_by_size_openness,
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
        "points": _rect(x, y, w, h),
        "sam3_class": cls,
        "collision_mode": "canopy" if canopy else "solid",
    }


def _cfg(**overrides) -> SpeckCullConfig:
    base = SpeckCullConfig(
        floor_area=150,
        ceiling_area=600,
        k=1.0,
        radius=100,
        analysis_stride=1,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


CANVAS = (512, 512)


def test_tiny_blob_dropped_even_when_not_open():
    # 10x10 rock (area 100 < floor 150) packed right next to a big cliff -> low
    # openness, but the floor drops it regardless of openness.
    survivors, stats = filter_specks_by_size_openness(
        [_poly("rock", 250, 250, 10, 10), _poly("cliff", 60, 60, 180, 180)],
        image_size=CANVAS,
        config=_cfg(),
    )
    classes = {p["sam3_class"] for p in survivors}
    assert classes == {"cliff"}
    assert stats["dropped"] == 1


def test_small_blob_in_open_ground_dropped():
    # 20x20 rock (area 400) alone in open space -> openness ~1 -> required ~ceiling
    # (600) -> 400 < 600 -> dropped.
    survivors, stats = filter_specks_by_size_openness(
        [_poly("rock", 250, 250, 20, 20)],
        image_size=CANVAS,
        config=_cfg(),
    )
    assert survivors == []
    assert stats["dropped"] == 1


def test_small_blob_packed_in_mass_kept():
    # Same 20x20 rock, but a big cliff fills its neighborhood (different class, so
    # the rock is still its own blob) -> low openness -> required ~floor (150) ->
    # 400 > 150 -> kept.
    survivors, stats = filter_specks_by_size_openness(
        [_poly("rock", 250, 250, 20, 20), _poly("cliff", 80, 80, 360, 360)],
        image_size=CANVAS,
        config=_cfg(),
    )
    classes = {p["sam3_class"] for p in survivors}
    assert classes == {"rock", "cliff"}
    assert stats["dropped"] == 0


def test_big_blob_alone_kept():
    # 40x40 rock (area 1600 > ceiling 600) alone in the open -> always kept.
    survivors, stats = filter_specks_by_size_openness(
        [_poly("rock", 250, 250, 40, 40)],
        image_size=CANVAS,
        config=_cfg(),
    )
    assert len(survivors) == 1
    assert stats["dropped"] == 0


def test_tree_never_dropped():
    # Tiny lone tree -> canopy, never a candidate.
    survivors, stats = filter_specks_by_size_openness(
        [_poly("tree", 250, 250, 10, 10, canopy=True)],
        image_size=CANVAS,
        config=_cfg(),
    )
    assert len(survivors) == 1
    assert stats["dropped"] == 0


def test_lone_cliff_fragment_dropped_like_any_class():
    # No class whitelist: a small lone cliff fragment in the open is culled too.
    survivors, stats = filter_specks_by_size_openness(
        [_poly("cliff", 250, 250, 20, 20)],
        image_size=CANVAS,
        config=_cfg(),
    )
    assert survivors == []
    assert stats["dropped"] == 1


def test_fragment_touching_parent_kept():
    # A small cliff fragment overlapping its big cliff parent fuses into one large
    # blob (per-class CC) -> blob area >> ceiling -> both kept.
    survivors, stats = filter_specks_by_size_openness(
        [_poly("cliff", 60, 60, 180, 180), _poly("cliff", 235, 120, 20, 20)],
        image_size=CANVAS,
        config=_cfg(),
    )
    assert len(survivors) == 2
    assert stats["dropped"] == 0
