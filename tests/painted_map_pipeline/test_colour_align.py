from __future__ import annotations

import numpy as np
from PIL import Image

from tools.painted_map_pipeline.world_levels.colour_align import (
    align_to_paired_padding,
)


def _scene(height=80, width=160, join=60):
    palette = np.asarray(
        [
            (12, 58, 104),
            (28, 82, 132),
            (92, 132, 164),
            (188, 210, 224),
        ],
        dtype=np.uint8,
    )
    target_palette = np.asarray(
        [
            (34, 78, 118),
            (52, 104, 146),
            (112, 148, 176),
            (204, 220, 230),
        ],
        dtype=np.uint8,
    )
    yy, xx = np.indices((height, width))
    classes = (xx // 8 + yy // 8) % len(palette)
    source_rgb = palette[classes]
    source = np.dstack((source_rgb, np.full((height, width), 255, dtype=np.uint8)))
    locked = np.zeros((height, width), dtype=np.uint8)
    pending = np.zeros_like(locked)
    locked[:, :join] = 255
    pending[:, join:] = 255
    accepted = np.zeros_like(source_rgb)
    accepted[:, :join] = target_palette[classes[:, :join]]
    return source, accepted, locked, pending, join, target_palette[classes]


def test_paired_colour_alignment_maps_new_art_and_preserves_geometry():
    source, accepted, locked, pending, join, expected = _scene()
    source[20:30, join + 20 : join + 30, :3] = 0
    painted_pending = (pending > 0) & (source[..., :3].sum(axis=2) > 20)
    before_error = np.abs(
        source[painted_pending, :3].astype(np.int16) - expected[painted_pending].astype(np.int16)
    ).mean()

    aligned, info = align_to_paired_padding(
        Image.fromarray(source),
        Image.fromarray(accepted),
        Image.fromarray(locked),
        Image.fromarray(pending),
    )
    result = np.asarray(aligned)
    after_error = np.abs(
        result[painted_pending, :3].astype(np.int16) - expected[painted_pending].astype(np.int16)
    ).mean()

    assert after_error < before_error * 0.35
    assert np.array_equal(result[:, :join], source[:, :join])
    assert np.all(result[20:30, join + 20 : join + 30, :3] == 0)
    assert info["corrected_pixels"] == int(painted_pending.sum())
    assert info["strength"] == 1.0
    accepted_colours = {tuple(int(v) for v in colour) for colour in accepted[accepted.sum(2) > 20]}
    used = {tuple(int(v) for v in colour) for colour in result[painted_pending][:, :3]}
    assert used <= accepted_colours


def test_alignment_learns_from_raw_after_the_cut_erases_the_overlap():
    raw, accepted, locked, pending, join, expected = _scene()
    cut = raw.copy()
    cut[:, :join, :3] = 0
    cut[20:30, join + 20 : join + 30, :3] = 0
    painted_pending = (pending > 0) & (cut[..., :3].sum(axis=2) > 20)
    before_error = np.abs(
        cut[painted_pending, :3].astype(np.int16) - expected[painted_pending].astype(np.int16)
    ).mean()

    aligned, info = align_to_paired_padding(
        Image.fromarray(cut),
        Image.fromarray(accepted),
        Image.fromarray(locked),
        Image.fromarray(pending),
        raw=Image.fromarray(raw),
    )
    result = np.asarray(aligned)
    after_error = np.abs(
        result[painted_pending, :3].astype(np.int16) - expected[painted_pending].astype(np.int16)
    ).mean()

    assert after_error < before_error * 0.35
    assert np.all(result[:, :join, :3] == 0)
    assert np.all(result[20:30, join + 20 : join + 30, :3] == 0)
    assert info["corrected_pixels"] == int(painted_pending.sum())
    accepted_colours = {tuple(int(v) for v in colour) for colour in accepted[accepted.sum(2) > 20]}
    used = {tuple(int(v) for v in colour) for colour in result[painted_pending][:, :3]}
    assert used <= accepted_colours
