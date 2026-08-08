"""Tests for the renderer seam: what the model is shown, and how the return is placed."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tools.painted_map_pipeline.world_levels.frames import Frame
from tools.painted_map_pipeline.world_levels.renderers import (
    FrameRenderer,
    PlaceContext,
    RequestContext,
    WarpRenderer,
    get_renderer,
)
from tools.painted_map_pipeline.world_levels.renderers.frame import (
    measure_drift,
    shift_image,
)
from tools.painted_map_pipeline.world_levels.renderers.warp import build_refine_prompt

CANVAS = (200, 160)
FRAME = Frame(20, 20, 160, 120)
OUTSIDE = (0, 0, 0, 255)


def _texture(size: tuple[int, int], seed: int = 7) -> Image.Image:
    """Deterministic high-frequency noise, so phase correlation has something to lock onto."""
    rng = np.random.default_rng(seed)
    pixels = rng.integers(40, 240, size=(size[1], size[0], 3), dtype=np.uint8)
    rgba = np.dstack([pixels, np.full((size[1], size[0]), 255, dtype=np.uint8)])
    return Image.fromarray(rgba, mode="RGBA")


def _mask(box: tuple[int, int, int, int], size: tuple[int, int] = CANVAS) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    return mask


def _request_context(**overrides) -> RequestContext:
    defaults = dict(
        level_id="01",
        canvas_size=CANVAS,
        frame=FRAME,
        outside_color=OUTSIDE,
        generation_input=_texture(CANVAS),
        generation_mask=_mask((60, 50, 139, 109)),
        locked_pixels=_texture(CANVAS, seed=3),
        locked_mask=_mask((30, 30, 69, 129)),
        locator=_texture((40, 30), seed=11),
        style_prompt="Test style.",
    )
    defaults.update(overrides)
    return RequestContext(**defaults)


def _place_context(**overrides) -> PlaceContext:
    defaults = dict(
        level_id="01",
        canvas_size=CANVAS,
        frame=FRAME,
        outside_color=OUTSIDE,
        generation_mask=_mask((60, 50, 139, 109)),
        locked_mask=_mask((30, 30, 69, 129)),
        sent_input=_texture(FRAME.size),
    )
    defaults.update(overrides)
    return PlaceContext(**defaults)


def test_get_renderer_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="unknown renderer"):
        get_renderer("nonsense")


# --- warp -------------------------------------------------------------------------------


def test_warp_masks_the_input_to_the_polygon_itself():
    # The masking moved out of refresh_level into here. generation_input.png stays dense so
    # the frame renderer can crop it; this is where the silhouette presentation happens.
    ctx = _request_context()
    request = WarpRenderer().request(ctx)
    sent = dict((item.role, image) for item, image in request.images)["terrain"]

    mask = np.asarray(ctx.generation_mask) > 0
    sent_array = np.asarray(sent)
    assert np.array_equal(sent_array[mask], np.asarray(ctx.generation_input)[mask])
    assert np.all(sent_array[~mask] == np.array(OUTSIDE))
    assert request.size == CANVAS


def test_warp_roster_carries_the_silhouette_and_drops_padding_when_there_is_none():
    with_padding = WarpRenderer().request(_request_context())
    assert [item.role for item, _ in with_padding.images] == [
        "terrain",
        "silhouette",
        "padding",
        "locator",
    ]

    seed = WarpRenderer().request(_request_context(locked_mask=Image.new("L", CANVAS, 0)))
    assert [item.role for item, _ in seed.images] == ["terrain", "silhouette", "locator"]


def test_prompt_numbering_matches_the_roster_it_was_built_from():
    for renderer in (WarpRenderer(), FrameRenderer()):
        request = renderer.request(_request_context())
        for index in range(1, len(request.images) + 1):
            assert f"Image {index} is" in request.prompt
        assert f"Image {len(request.images) + 1} is" not in request.prompt
        assert request.prompt.isascii()


def test_refine_prompt_does_not_reframe_the_task_as_creation():
    prompt = build_refine_prompt(
        [item for item, _ in WarpRenderer().request(_request_context()).images]
    ).lower()
    for banned in ("create", "generate", "invent"):
        assert banned not in prompt


# --- frame ------------------------------------------------------------------------------


def test_frame_sends_a_crop_at_the_frame_size_with_no_silhouette():
    ctx = _request_context()
    request = FrameRenderer().request(ctx)

    assert [item.role for item, _ in request.images] == ["terrain", "padding", "locator"]
    assert request.size == FRAME.size
    sent = dict((item.role, image) for item, image in request.images)["terrain"]
    assert sent.size == FRAME.size
    assert np.array_equal(np.asarray(sent), np.asarray(ctx.generation_input.crop(FRAME.box)))
    # No silhouette language at all: the frame is painted edge to edge and we do the cutting.
    assert "black" not in request.prompt.lower()


def test_frame_place_reproduces_the_input_inside_the_polygon():
    ctx = _place_context()
    normalized, info = FrameRenderer().place(ctx.sent_input, ctx)

    assert normalized.size == CANVAS
    mask = np.asarray(ctx.generation_mask) > 0
    expected = Image.new("RGBA", CANVAS, OUTSIDE)
    expected.paste(ctx.sent_input, (FRAME.left, FRAME.top))
    assert np.array_equal(np.asarray(normalized)[mask], np.asarray(expected)[mask])
    assert np.all(np.asarray(normalized)[~mask] == np.array(OUTSIDE))
    assert info["drift_applied"] is False


def test_frame_place_refuses_a_size_the_provider_was_not_asked_for():
    # No warp stands behind this to rescue a wrong size, so it must be fatal rather than
    # quietly resized -- resizing is the distortion this renderer exists to remove.
    ctx = _place_context()
    with pytest.raises(ValueError, match="expected the frame size"):
        FrameRenderer().place(_texture((100, 100)), ctx)


def test_frame_place_corrects_a_shifted_return():
    ctx = _place_context()
    clean, _ = FrameRenderer().place(ctx.sent_input, ctx)
    shifted, info = FrameRenderer().place(shift_image(ctx.sent_input, 4, 3), ctx)

    assert info["drift_applied"] is True
    assert info["drift_px"] == [4, 3]
    # Registered back into place: what lands inside the polygon matches the unshifted case.
    # Compared away from the frame border, where edge replication legitimately differs.
    mask = np.asarray(_mask((70, 60, 129, 99))) > 0
    assert np.array_equal(np.asarray(clean)[mask], np.asarray(shifted)[mask])


def test_drift_is_not_measured_without_padding_to_register_against():
    # The first level accepted has no padding and needs no correction: whatever it paints
    # becomes the truth and every neighbour copies from it.
    (dx, dy), info = measure_drift(
        _texture(FRAME.size), _texture(FRAME.size, seed=9), Image.new("L", FRAME.size, 0)
    )
    assert (dx, dy) == (0, 0)
    assert info["drift_applied"] is False
    assert "no padding" in info["drift_reason"]


def test_an_implausible_drift_estimate_falls_back_to_no_correction():
    # Applying a wrong shift confidently is worse than applying none.
    sent = _texture(FRAME.size)
    padding = _mask((10, 10, 149, 109), size=FRAME.size)
    (dx, dy), info = measure_drift(sent, shift_image(sent, 40, 0), padding)
    assert (dx, dy) == (0, 0)
    assert info["drift_applied"] is False
    assert "sanity limit" in info["drift_reason"]


def test_shift_moves_content_in_the_direction_it_is_named_for():
    source = _texture((40, 30))
    shifted = np.asarray(shift_image(source, 5, 2))
    original = np.asarray(source)
    # Positive means right and down: the pixel at (x, y) reappears at (x + 5, y + 2).
    assert np.array_equal(shifted[2 + 3, 5 + 7], original[3, 7])


def test_shift_replicates_the_edge_rather_than_filling_with_black():
    # The polygon can sit close to the frame border, so pulling outside_color in would punch
    # a hole in the art.
    shifted = np.asarray(shift_image(_texture((40, 30)), 5, 0))
    assert not np.any(np.all(shifted == np.array(OUTSIDE), axis=2))
