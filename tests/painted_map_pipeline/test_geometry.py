from __future__ import annotations

import numpy as np
import pytest

from tools.painted_map_pipeline.world_levels import geometry as g


def test_polygon_area_and_bbox():
    square = ((0, 0), (10, 0), (10, 10), (0, 10))
    assert g.polygon_area(square) == 100.0
    triangle = ((0, 0), (10, 0), (0, 10))
    assert g.polygon_area(triangle) == 50.0
    assert g.polygon_bbox(square) == (0, 0, 10, 10)
    # Area is winding-order independent.
    assert g.polygon_area(tuple(reversed(square))) == 100.0


def test_validate_simple_polygon_matches_plan_loader_behavior():
    # These are the exact failure modes plan_loader relied on before the lift.
    colinear = ((0, 0), (1, 0), (2, 0))
    with pytest.raises(ValueError, match="zero area"):
        g.validate_simple_polygon(colinear, "core polygon", "07")
    # Self-intersecting with non-zero signed area, so it reaches the self-intersect branch
    # (a symmetric bowtie has zero area and would trip the earlier check instead).
    crossed = ((0, 0), (8, 10), (0, 10), (10, 0))
    with pytest.raises(ValueError, match="self-intersects"):
        g.validate_simple_polygon(crossed, "core polygon", "07")
    # A valid polygon does not raise.
    g.validate_simple_polygon(((0, 0), (10, 0), (10, 10), (0, 10)), "core polygon", "07")


def test_mask_to_polygon_recovers_a_square():
    mask = np.zeros((20, 20), dtype=bool)
    mask[4:16, 4:16] = True  # 12x12 filled block
    poly = g.mask_to_polygon(mask, epsilon_frac=0.01)
    assert len(poly) >= 4
    left, top, right, bottom = g.polygon_bbox(poly)
    assert abs(left - 4) <= 2 and abs(top - 4) <= 2
    assert abs(right - 15) <= 2 and abs(bottom - 15) <= 2
    assert g.polygon_area(poly) > 100  # ~144, allowing for contour simplification


def test_largest_component_and_dilation():
    mask = np.zeros((20, 40), dtype=bool)
    mask[2:6, 2:6] = True     # small blob (16 px)
    mask[2:12, 20:30] = True  # large blob (100 px)
    largest = g.largest_connected_component(mask)
    assert largest[5, 25]        # inside the large blob
    assert not largest[3, 3]     # small blob removed
    single = np.zeros((11, 11), dtype=bool)
    single[5, 5] = True
    grown = g.dilate_mask(single, 2)
    assert int(grown.sum()) > 1
    assert g.dilate_mask(single, 0).sum() == 1  # radius 0 is a no-op
