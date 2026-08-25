from __future__ import annotations

import cv2
import numpy as np

from tools.painted_map_pipeline.world_levels.masks import rasterize_polygon
from tools.painted_map_pipeline.world_levels.topology import partition_to_polygons


def _assert_tiles(labels, polygons, max_vertices):
    """Perfect tiling: full coverage (no gaps), no area overlap, no spill outside the chunk.
    Coverage is checked with inclusive rasterization; overlap/spill with *strictly-inside*
    point-in-polygon so a shared diagonal edge (an inherent ~1px band) is not miscounted."""
    h, w = labels.shape
    chunk = labels > 0
    total = int(chunk.sum())
    contours = {r: np.asarray(p, dtype=np.int32).reshape(-1, 1, 2) for r, p in polygons.items()}

    # Coverage: union of rasterized polygons must cover the chunk.
    covered = np.zeros((h, w), dtype=bool)
    for poly in polygons.values():
        covered |= np.asarray(rasterize_polygon((w, h), list(poly))) > 0
    assert int((covered & chunk).sum()) / total > 0.995, "coverage gap: chunk not fully covered"

    # Area overlap / spill: only points STRICTLY inside a polygon (> 0) count, so shared edges
    # and the 1px fill-outline don't register.
    overlaps = spill = 0
    for r in range(h):
        for c in range(w):
            strictly_in = sum(1 for cnt in contours.values()
                              if cv2.pointPolygonTest(cnt, (c + 0.5, r + 0.5), False) > 0)
            if chunk[r, c]:
                overlaps += strictly_in > 1
            else:
                spill += strictly_in > 0
    assert overlaps / total < 0.01, f"overlap: {overlaps}/{total} chunk pixels strictly in >1 region"
    assert spill / total < 0.01, f"spill: {spill} pixels outside the chunk strictly inside a region"
    for poly in polygons.values():
        assert len(poly) <= max_vertices, f"polygon has {len(poly)} > {max_vertices} vertices"


def test_two_regions_tile_exactly():
    labels = np.zeros((40, 50), dtype=np.int32)
    labels[5:35, 5:45] = 1
    labels[5:35, 25:45] = 2  # right half of the chunk is region 2
    polygons = partition_to_polygons(labels, smooth_kernel=1, simplify_outer=False, tolerance=2.0)
    assert set(polygons) == {1, 2}
    _assert_tiles(labels, polygons, max_vertices=12)


def test_three_regions_triple_point():
    labels = np.zeros((60, 60), dtype=np.int32)
    labels[6:54, 6:54] = 1              # whole chunk starts as region 1
    labels[6:30, 30:54] = 2            # top-right quadrant -> region 2
    labels[30:54, 30:54] = 3          # bottom-right quadrant -> region 3
    # region 1 = left half; 2 = top-right; 3 = bottom-right; triple point near (30,30)
    polygons = partition_to_polygons(labels, smooth_kernel=1, simplify_outer=False, tolerance=2.0)
    assert set(polygons) == {1, 2, 3}
    _assert_tiles(labels, polygons, max_vertices=12)


def test_diagonal_boundary_stays_simple():
    # A slanted boundary (staircased at pixel level) should de-staircase to few vertices.
    labels = np.zeros((60, 60), dtype=np.int32)
    for r in range(6, 54):
        for c in range(6, 54):
            labels[r, c] = 1 if c < r else 2
    polygons = partition_to_polygons(labels, smooth_kernel=1, simplify_outer=False, tolerance=2.0)
    assert set(polygons) == {1, 2}
    _assert_tiles(labels, polygons, max_vertices=12)
