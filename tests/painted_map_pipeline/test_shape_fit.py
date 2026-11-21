"""The shape fit behind the review page's holes count and Fit shape button."""

from __future__ import annotations

import numpy as np
from PIL import Image

from tools.painted_map_pipeline.world_levels.renderers.frame import shift_image
from tools.painted_map_pipeline.world_levels.shape_fit import ShapeFit, shift_mask

H, W = 120, 200


def _scene(drift=(3, -2)):
    """Land drawn ``drift`` px off its shape (right, down), with a dark crevice inside it."""
    shape = np.zeros((H, W), dtype=bool)
    shape[30:90, 50:150] = True
    raw = np.zeros((H, W, 3), dtype=np.uint8)
    dx, dy = drift
    raw[30 + dy : 90 + dy, 50 + dx : 150 + dx] = (120, 150, 180)
    raw[55:60, 90:100] = (4, 4, 6)
    return raw, shape


def test_shift_mask_moves_like_the_placement_does():
    raw, _ = _scene()
    painted = raw.sum(axis=2) > 40
    moved = np.asarray(shift_image(Image.fromarray(raw), -7, 4))[..., :3].sum(axis=2) > 40
    assert np.array_equal(shift_mask(painted, -7, 4), moved)


def test_holes_count_only_black_joined_to_the_outside():
    raw, shape = _scene(drift=(0, 0))
    fit = ShapeFit(raw, shape, shape)
    assert fit.score((0, 0))["missing_px"] == 0  # the crevice is art


def test_the_best_offset_puts_the_drifted_picture_back():
    raw, shape = _scene(drift=(3, -2))
    fit = ShapeFit(raw, shape, shape)
    assert fit.score((0, 0))["missing_px"] > 0
    best = fit.best()
    # Drawn 3 right and 2 up: the picture moves back by (-3, +2), i.e. the offset is (3, -2).
    assert best["offset"] == [3, -2]
    assert best["missing_px"] == 0 and best["cut_iou"] == 1.0


def test_only_the_new_cell_counts_the_padding_covers_the_rest():
    raw, shape = _scene(drift=(3, 0))
    cell = shape.copy()
    cell[:, :100] = False  # the left half is padding
    fit = ShapeFit(raw, shape, cell)
    assert fit.score((0, 0))["missing_px"] == 0  # the hole is on the left edge, under the padding
