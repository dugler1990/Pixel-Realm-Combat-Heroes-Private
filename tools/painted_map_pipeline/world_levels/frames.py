"""The rectangle of canvas a renderer asks the model to paint.

The canvas is sized to hold the *largest* level crop, so every other level sits on it
surrounded by black -- 58-88% of the canvas for the crops in the current plan, and 71-91%
once the polygon mask is applied. Sending that is what makes a model crop to the content
and stretch it to fill, which is the reframing this whole path exists to avoid.

A frame is the level's own crop, grown only as far as the provider's size rules demand and
then filled with more world map rather than more black. Requesting exactly the frame's pixel
size means the return can be pasted back at an integer offset with no resize anywhere.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .coordinates import ScaledSpace
from .models import LevelTransform


@dataclass(frozen=True)
class FrameConstraints:
    """Provider limits on a generation size. Defaults impose nothing."""

    edge_multiple: int = 1
    max_edge: int | None = None
    min_pixels: int | None = None
    max_pixels: int | None = None
    max_aspect: float | None = None


@dataclass(frozen=True)
class Frame:
    """A rectangle on the canvas, in canvas pixels."""

    left: int
    top: int
    width: int
    height: int

    @property
    def box(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.left + self.width, self.top + self.height

    @property
    def size(self) -> tuple[int, int]:
        return self.width, self.height

    def as_dict(self) -> dict[str, Any]:
        return {"origin": [self.left, self.top], "size": [self.width, self.height]}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Frame":
        (left, top), (width, height) = value["origin"], value["size"]
        return cls(int(left), int(top), int(width), int(height))


def constraints_for(generation: dict[str, Any]) -> FrameConstraints:
    """Size rules for the configured provider.

    Unknown providers get no rules at all, which keeps the tiny canvases used by the tests
    workable -- gpt-image-2's 655k-pixel minimum is larger than the whole fixture world.
    """
    provider = str(generation.get("provider") or "").strip().lower()
    if provider == "openai":
        from ..openai_api import EDGE_MULTIPLE, MAX_ASPECT, MAX_EDGE, MAX_PIXELS, MIN_PIXELS

        return FrameConstraints(
            edge_multiple=EDGE_MULTIPLE,
            max_edge=MAX_EDGE,
            min_pixels=MIN_PIXELS,
            max_pixels=MAX_PIXELS,
            max_aspect=MAX_ASPECT,
        )
    return FrameConstraints()


def _round_up(value: int, multiple: int) -> int:
    if multiple <= 1:
        return value
    return int(math.ceil(value / multiple)) * multiple


def _grow_to_constraints(width: int, height: int, limits: FrameConstraints) -> tuple[int, int]:
    """Smallest size at or above (width, height) satisfying every rule.

    Only ever grows. Shrinking would mean resampling the art back down, which is the
    distortion this path exists to remove -- so a size that cannot be satisfied by growing
    is an error rather than something to quietly fix.
    """
    for _ in range(8):
        grown_w, grown_h = width, height
        if limits.max_aspect:
            if grown_w > grown_h * limits.max_aspect:
                grown_h = int(math.ceil(grown_w / limits.max_aspect))
            if grown_h > grown_w * limits.max_aspect:
                grown_w = int(math.ceil(grown_h / limits.max_aspect))
        if limits.min_pixels and grown_w * grown_h < limits.min_pixels:
            factor = math.sqrt(limits.min_pixels / (grown_w * grown_h))
            grown_w = int(math.ceil(grown_w * factor))
            grown_h = int(math.ceil(grown_h * factor))
        grown_w = _round_up(grown_w, limits.edge_multiple)
        grown_h = _round_up(grown_h, limits.edge_multiple)
        if (grown_w, grown_h) == (width, height):
            break
        width, height = grown_w, grown_h
    return width, height


def _check_upper_limits(width: int, height: int, limits: FrameConstraints, level_id: str) -> None:
    if limits.max_edge and max(width, height) > limits.max_edge:
        raise ValueError(
            f"level {level_id}: frame {width}x{height} exceeds the provider's "
            f"{limits.max_edge}px maximum edge"
        )
    if limits.max_pixels and width * height > limits.max_pixels:
        raise ValueError(
            f"level {level_id}: frame {width}x{height} is {width * height} pixels, over the "
            f"provider's {limits.max_pixels} maximum"
        )


def derive_frame(
    transform: LevelTransform,
    limits: FrameConstraints,
    *,
    level_id: str = "",
) -> Frame:
    """The level's crop on the canvas, grown to a legal generation size and centred on it.

    Deliberately derived rather than folded back into ``LevelSpec``: ``_validate_spec``
    requires every polygon point to sit inside its crop and the crop to sit inside the world
    image, so a mutated crop box would either trip those checks or move every canvas offset.
    Keeping the frame derived leaves the canvas geometry -- offsets, masks, overlaps --
    byte-identical to a run that never uses frames at all.
    """
    canvas_w, canvas_h = transform.canvas_width, transform.canvas_height
    width, height = _grow_to_constraints(
        transform.scaled_crop_width, transform.scaled_crop_height, limits
    )
    _check_upper_limits(width, height, limits, level_id)
    if width > canvas_w or height > canvas_h:
        raise ValueError(
            f"level {level_id}: frame {width}x{height} does not fit the canvas {canvas_w}x{canvas_h}"
        )

    # Centre the grown frame on the crop it came from, then slide it back inside the canvas.
    # The crop already fits, so a clamp can only be needed on one side per axis.
    center_x = transform.canvas_offset_x + transform.scaled_crop_width // 2
    center_y = transform.canvas_offset_y + transform.scaled_crop_height // 2
    left = min(max(center_x - width // 2, 0), canvas_w - width)
    top = min(max(center_y - height // 2, 0), canvas_h - height)
    return Frame(left, top, width, height)


def world_box_covering(
    frame: Frame,
    transform: LevelTransform,
    scaled: ScaledSpace,
    world_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Smallest world-image box whose scaled render covers ``frame``, clamped to the world.

    Expansion takes more world map rather than more black. Where the world edge stops it, the
    caller is left with ``outside_color`` on that side -- bounded, and the only black the
    model sees under the frame renderer.
    """
    # Frame corners back into the shared scaled-world space the transform maps from.
    scaled_left = frame.left - transform.canvas_offset_x + transform.scaled_crop_left
    scaled_top = frame.top - transform.canvas_offset_y + transform.scaled_crop_top
    scaled_right = scaled_left + frame.width
    scaled_bottom = scaled_top + frame.height

    world_w, world_h = world_size
    left, top = 0, 0
    right, bottom = world_w, world_h
    # Walk each edge inward while the scaled render still covers the frame. Scale is a
    # Decimal with rounding, so stepping through the same coordinate function the rest of the
    # pipeline uses is exact where arithmetic on the ratio would not be.
    while left + 1 <= right and scaled.coordinate(left + 1) <= scaled_left:
        left += 1
    while top + 1 <= bottom and scaled.coordinate(top + 1) <= scaled_top:
        top += 1
    while right - 1 >= left and scaled.coordinate(right - 1) >= scaled_right:
        right -= 1
    while bottom - 1 >= top and scaled.coordinate(bottom - 1) >= scaled_bottom:
        bottom -= 1
    return left, top, right, bottom
