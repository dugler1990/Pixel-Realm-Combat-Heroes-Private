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
    # Under the padding the model's own pixels are recoloured too (the padding is pasted
    # over them later; a feather fades into them), so there they become padding colours.
    assert np.array_equal(result[:, :join, :3], accepted[:, :join])
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


def _noise_scene(height=80, width=160, join=60, seed=5):
    """Per-pixel noise of the same four colours: a shift of even one pixel breaks most pairs.

    The 8 px checkerboard above keeps about half its pairs right under a small shift, which
    is enough for the per-bin median to recover, so it cannot show the drift doing harm.
    """
    source, accepted, locked, pending, join, _ = _scene(height, width, join)
    palette = np.unique(source[..., :3].reshape(-1, 3), axis=0)
    targets = np.unique(accepted[:, :join].reshape(-1, 3), axis=0)
    classes = np.random.default_rng(seed).integers(0, len(palette), (height, width))
    raw = np.dstack((palette[classes], np.full((height, width), 255, dtype=np.uint8)))
    accepted = np.zeros_like(accepted)
    accepted[:, :join] = targets[classes[:, :join]]
    return raw, accepted, locked, pending, targets[classes]


def _pending_error(image, expected, pending):
    painted = (pending > 0) & (image[..., :3].sum(axis=2) > 20)
    return np.abs(image[painted, :3].astype(np.int16) - expected[painted].astype(np.int16)).mean()


def test_drifted_pairs_fail_and_the_offset_puts_them_back():
    """The model drew everything (dx, dy) off; dragging the padding by the same fixes the map."""
    from tools.painted_map_pipeline.world_levels.result_ingest import _shift_black

    raw, accepted, locked, pending, expected = _noise_scene()
    dx, dy = 3, -2
    drifted = np.asarray(_shift_black(Image.fromarray(raw), dx, dy))
    before = _pending_error(raw, expected, pending)

    def aligned_with(pair_source):
        out, _ = align_to_paired_padding(
            Image.fromarray(raw), Image.fromarray(accepted), Image.fromarray(locked),
            Image.fromarray(pending), raw=pair_source,
        )
        return _pending_error(np.asarray(out), expected, pending)

    misaligned = aligned_with(Image.fromarray(drifted))
    corrected = aligned_with(_shift_black(Image.fromarray(drifted), -dx, -dy))
    assert misaligned > before * 0.35
    assert corrected < before * 0.35


def test_the_band_a_shift_opens_is_black():
    from tools.painted_map_pipeline.world_levels.result_ingest import _shift_black

    raw = _noise_scene()[0]
    shifted = np.asarray(_shift_black(Image.fromarray(raw), -3, 2))
    assert np.all(shifted[:2, :, :3] == 0)          # down 2: the top rows are new
    assert np.all(shifted[:, -3:, :3] == 0)         # left 3: the right columns are new
    assert np.array_equal(shifted[2:, :-3], raw[:-2, 3:])


def _flat_new_cell_scene(seed=3, height=120, width=240, join=80):
    """Padding with full contrast. The model's picture is darker, and only half of it follows
    the padding's detail -- the other half is detail of its own, as when the model drew things
    in slightly different places. Each colour group's median then sits between the two, which
    is what makes the swap grey."""
    import cv2

    rng = np.random.default_rng(seed)

    def field():
        f = cv2.GaussianBlur(rng.random((height, width)).astype(np.float32), (0, 0), 2)
        return (f - f.min()) / (f.max() - f.min())

    def blue(lightness):
        return np.stack([20 + 200 * lightness, 60 + 170 * lightness, 110 + 130 * lightness],
                        axis=-1).astype(np.uint8)

    padding_detail, own_detail = field(), field()
    raw_rgb = (blue(0.5 * padding_detail + 0.5 * own_detail).astype(np.float32) * 0.7 + 20)
    raw = np.dstack((raw_rgb.astype(np.uint8), np.full((height, width), 255, np.uint8)))
    locked = np.zeros((height, width), np.uint8)
    locked[:, :join] = 255
    accepted = np.zeros((height, width, 3), np.uint8)
    accepted[:, :join] = blue(padding_detail)[:, :join]
    return raw, accepted, locked, 255 - locked, join


def _lightness(rgb):
    import cv2

    return cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)


def test_match_restores_the_padding_contrast_the_swap_loses():
    raw, accepted, locked, pending, join = _flat_new_cell_scene()
    images = [Image.fromarray(a) for a in (raw, accepted, locked, pending)]
    padding_spread = _lightness(accepted[:, :join]).std()
    spreads = {}
    for method in ("swap", "match"):
        out, info = align_to_paired_padding(*images, method=method)
        assert info["method"] == method
        spreads[method] = _lightness(np.asarray(out)[:, join:, :3]).std() / padding_spread
    assert spreads["swap"] < 0.8
    assert abs(spreads["match"] - 1.0) < abs(spreads["swap"] - 1.0)
    assert abs(spreads["match"] - 1.0) < 0.1


def test_match_leaves_the_black_gaps_alone():
    raw, accepted, locked, pending, join = _flat_new_cell_scene()
    raw[10:20, join + 30 : join + 40, :3] = 0
    out, _ = align_to_paired_padding(*(Image.fromarray(a) for a in (raw, accepted, locked, pending)))
    assert not np.asarray(out)[10:20, join + 30 : join + 40, :3].any()


def test_both_sides_of_a_feathered_join_are_corrected():
    """The feather fades the padding into the model's pixels under it, so those are corrected
    the same way as the new cell; left raw they made a step at the join."""
    raw, accepted, locked, pending, join = _flat_new_cell_scene()
    out, info = align_to_paired_padding(*(Image.fromarray(a) for a in (raw, accepted, locked, pending)))
    out = np.asarray(out)
    under, new = _lightness(out[:, join - 6 : join, :3]).mean(), _lightness(out[:, join : join + 6, :3]).mean()
    raw_under = _lightness(raw[:, join - 6 : join, :3]).mean()
    assert info["corrected_under_padding"] == int((locked > 0).sum())
    assert abs(under - new) < abs(raw_under - new)


def test_an_unknown_colour_method_is_refused():
    import pytest

    raw, accepted, locked, pending, _ = _flat_new_cell_scene()
    with pytest.raises(ValueError, match="colour method"):
        align_to_paired_padding(*(Image.fromarray(a) for a in (raw, accepted, locked, pending)),
                                method="grade")
