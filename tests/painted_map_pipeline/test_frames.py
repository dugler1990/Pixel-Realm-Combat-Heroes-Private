"""Tests for the generation frame: the rectangle a renderer asks the model to paint."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.painted_map_pipeline.world_levels.config import load_config
from tools.painted_map_pipeline.world_levels.coordinates import (
    ScaledSpace,
    build_transform,
    resolve_canvas,
)
from tools.painted_map_pipeline.world_levels.frames import (
    FrameConstraints,
    constraints_for,
    derive_frame,
    world_box_covering,
)
from tools.painted_map_pipeline.world_levels.masks import build_level_masks
from tools.painted_map_pipeline.world_levels.models import LevelTransform
from tools.painted_map_pipeline.world_levels.plan_loader import load_level_plan

REAL_CONFIG = Path("tools/painted_map_pipeline/world_levels/frostreach.agent-test.json")

OPENAI = FrameConstraints(
    edge_multiple=16, max_edge=3840, min_pixels=655_000, max_pixels=8_300_000, max_aspect=3.0
)


def _transform(crop_w: int, crop_h: int, canvas: tuple[int, int]) -> LevelTransform:
    return LevelTransform(
        scale="5",
        scaled_crop_left=0,
        scaled_crop_top=0,
        scaled_crop_width=crop_w,
        scaled_crop_height=crop_h,
        canvas_offset_x=(canvas[0] - crop_w) // 2,
        canvas_offset_y=(canvas[1] - crop_h) // 2,
        canvas_width=canvas[0],
        canvas_height=canvas[1],
    )


def test_default_constraints_leave_a_frame_alone():
    # An unknown provider imposes nothing, which is what keeps the tiny fixture canvases
    # usable -- gpt-image-2's 655k-pixel minimum is bigger than the whole fixture world.
    frame = derive_frame(_transform(11, 9, (26, 22)), FrameConstraints())
    assert frame.size == (11, 9)


def test_frame_grows_to_the_edge_multiple_and_stays_centred():
    frame = derive_frame(_transform(1415, 1315, (3072, 2304)), OPENAI, level_id="03")
    assert frame.size == (1424, 1328)
    assert frame.box[2] <= 3072 and frame.box[3] <= 2304
    # Centred on the crop it came from, to within the rounding of an odd difference.
    assert abs(frame.left + frame.width // 2 - ((3072 - 1415) // 2 + 1415 // 2)) <= 1


def test_frame_grows_a_too_wide_crop_until_it_is_within_the_aspect_limit():
    # Level 18 is 3065x815, an aspect of 3.76 against a 3:1 limit, so it has to gain height.
    frame = derive_frame(_transform(3065, 815, (3072, 2304)), OPENAI, level_id="18")
    assert max(frame.size) / min(frame.size) <= 3.0
    assert frame.width % 16 == 0 and frame.height % 16 == 0


def test_frame_grows_a_small_crop_up_to_the_pixel_minimum():
    frame = derive_frame(_transform(760, 800, (3072, 2304)), OPENAI, level_id="25")
    assert frame.width * frame.height >= 655_000


def test_frame_that_cannot_fit_the_canvas_is_refused():
    with pytest.raises(ValueError, match="does not fit the canvas"):
        derive_frame(_transform(600, 600, (700, 700)), OPENAI, level_id="99")


def test_frame_over_the_provider_maximum_is_refused_rather_than_shrunk():
    # Shrinking would mean resampling the art back down, which is the distortion the frame
    # renderer exists to remove. An impossible size is an error, not something to fix quietly.
    with pytest.raises(ValueError, match="maximum edge"):
        derive_frame(_transform(3900, 1400, (4000, 2000)), OPENAI, level_id="99")


def test_constraints_come_from_the_provider():
    assert constraints_for({"provider": "openai"}).edge_multiple == 16
    assert constraints_for({"provider": "copy"}) == FrameConstraints()


def test_world_box_covers_a_frame_away_from_the_world_edges():
    scaled = ScaledSpace(5)
    transform = _transform(1415, 1315, (3072, 2304))
    # Put the crop well inside the world so the expansion has real map to take on every side.
    transform = LevelTransform(
        **{**transform.__dict__, "scaled_crop_left": 4020, "scaled_crop_top": 270}
    )
    frame = derive_frame(transform, OPENAI, level_id="03")
    left, top, right, bottom = world_box_covering(frame, transform, scaled, (1536, 1024))

    assert 0 <= left < right <= 1536
    assert 0 <= top < bottom <= 1024
    # The scaled render of that world box has to reach every edge of the frame, or the frame
    # would be filled with black where the map ran out.
    scaled_left = frame.left - transform.canvas_offset_x + transform.scaled_crop_left
    scaled_top = frame.top - transform.canvas_offset_y + transform.scaled_crop_top
    assert scaled.coordinate(left) <= scaled_left
    assert scaled.coordinate(top) <= scaled_top
    assert scaled.coordinate(right) >= scaled_left + frame.width
    assert scaled.coordinate(bottom) >= scaled_top + frame.height


def test_world_box_clamps_rather_than_reading_past_the_world_edge():
    # A frame whose expansion runs off the map cannot be filled entirely; the deficit stays
    # outside_color. Bounded, and only at the world's own borders.
    scaled = ScaledSpace(5)
    transform = _transform(1415, 1315, (3072, 2304))
    frame = derive_frame(transform, OPENAI, level_id="03")
    left, top, right, bottom = world_box_covering(frame, transform, scaled, (1536, 1024))
    assert (left, top) == (0, 0)
    assert right <= 1536 and bottom <= 1024


@pytest.mark.skipif(not REAL_CONFIG.is_file(), reason="real level plan not present")
def test_every_real_level_frame_is_legal_and_contains_its_polygon():
    """Verification step 3, asserted per level and with no API calls.

    Level 18 expands to exactly the canvas width at zero margin, so it passes by nothing --
    a level-plan change would break it silently without this.
    """
    import numpy as np

    config = load_config(REAL_CONFIG)
    levels = load_level_plan(config.level_plan, (1536, 1024))
    scaled = ScaledSpace(config.scale)
    canvas_size = resolve_canvas(config.canvas, levels, scaled)
    limits = constraints_for({"provider": "openai"})

    for level_id, level in levels.items():
        transform = build_transform(level, scaled, config.canvas, canvas_size)
        frame = derive_frame(transform, limits, level_id=level_id)

        assert frame.width % 16 == 0 and frame.height % 16 == 0, level_id
        assert max(frame.size) <= 3840, level_id
        assert 655_000 <= frame.width * frame.height <= 8_300_000, level_id
        assert max(frame.size) / min(frame.size) <= 3.0, level_id
        assert frame.left >= 0 and frame.top >= 0, level_id
        assert frame.box[2] <= canvas_size[0] and frame.box[3] <= canvas_size[1], level_id

        # The cut only works because the frame holds the whole polygon. plan_loader enforces
        # that every polygon point sits inside its crop, and the frame only ever grows from
        # there -- this is the assertion that keeps that chain honest.
        _, generation = build_level_masks(level, scaled, transform)
        ys, xs = np.nonzero(np.asarray(generation) > 0)
        assert xs.min() >= frame.left and xs.max() < frame.box[2], level_id
        assert ys.min() >= frame.top and ys.max() < frame.box[3], level_id
