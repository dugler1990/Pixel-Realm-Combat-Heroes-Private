"""Tests for the pre-warp rescale that recovers reframed generations."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from tools.painted_map_pipeline.world_levels.land_fit import (
    content_bbox,
    footprint_iou,
    is_full_bleed,
    rescale_to_mask,
)

CANVAS = (200, 140)
# Land sits well inside the canvas, so there is a real letterbox to discard.
POLYGON = [(60, 40), (140, 36), (156, 78), (120, 104), (52, 96)]


def _mask(size: tuple[int, int] = CANVAS, polygon: list[tuple[int, int]] | None = None) -> Image.Image:
    from PIL import ImageDraw

    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(polygon or POLYGON, fill=255)
    return mask


def _painted(mask: Image.Image) -> Image.Image:
    """Colour the mask so every land pixel is clearly above the content threshold."""
    array = np.asarray(mask) > 0
    rgba = np.zeros((*array.shape, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    rgba[array] = (120, 160, 210, 255)
    return Image.fromarray(rgba, mode="RGBA")


def _reframed(mask: Image.Image) -> Image.Image:
    """The failure mode: land cropped to its bbox and stretched to fill the canvas."""
    box = content_bbox(_painted(mask))
    return _painted(mask).crop(box).resize(CANVAS, Image.NEAREST)


def test_rescale_lands_content_exactly_on_the_mask_bbox():
    mask = _mask()
    rescaled, info = rescale_to_mask(_reframed(mask), mask)

    target = info["target_bbox"]
    assert content_bbox(rescaled) == tuple(target)
    assert info["scale_x"] < 1.0 and info["scale_y"] < 1.0
    # bbox aspect differs from canvas aspect, so the two axes must scale differently
    assert info["scale_x"] != info["scale_y"]


def test_rescale_recovers_a_reframed_render():
    mask = _mask()
    reframed = _reframed(mask)
    before = footprint_iou(reframed, mask)
    rescaled, _ = rescale_to_mask(reframed, mask)
    after = footprint_iou(rescaled, mask)

    assert before < 0.5, f"fixture should start badly reframed, got {before}"
    assert after > 0.9, f"rescale should recover the footprint, got {after}"


def test_correctly_framed_render_is_already_above_threshold():
    mask = _mask()
    assert footprint_iou(_painted(mask), mask) > 0.99
    assert not is_full_bleed(_painted(mask))


def test_full_bleed_is_detected():
    assert is_full_bleed(Image.new("RGBA", CANVAS, (120, 160, 210, 255)))


def test_reframed_render_is_not_full_bleed():
    # A crop-and-stretch reframe touches all four borders by construction, but it still
    # has plenty of black and rescales cleanly. It must not be treated as unrecoverable.
    reframed = _reframed(_mask())
    assert reframed.getpixel((0, 0))[:3] == (0, 0, 0)
    assert not is_full_bleed(reframed)


def test_content_bbox_ignores_a_stray_speck():
    mask = _mask()
    clean = _painted(mask)
    speckled = clean.copy()
    speckled.putpixel((3, 3), (200, 200, 200, 255))

    assert content_bbox(speckled) == content_bbox(clean)


def test_stray_speck_does_not_change_the_rescale():
    mask = _mask()
    reframed = _reframed(mask)
    speckled = reframed.copy()
    speckled.putpixel((1, CANVAS[1] - 2), (200, 200, 200, 255))

    _, clean_info = rescale_to_mask(reframed, mask)
    _, speckled_info = rescale_to_mask(speckled, mask)
    assert clean_info["scale_x"] == speckled_info["scale_x"]
    assert clean_info["scale_y"] == speckled_info["scale_y"]


def test_rescale_rejects_an_empty_generation():
    with pytest.raises(ValueError, match="no non-black content"):
        rescale_to_mask(Image.new("RGBA", CANVAS, (0, 0, 0, 255)), _mask())


def test_rescale_rejects_an_empty_mask():
    with pytest.raises(ValueError, match="mask is empty"):
        rescale_to_mask(_painted(_mask()), Image.new("L", CANVAS, 0))
