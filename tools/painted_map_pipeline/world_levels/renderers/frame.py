"""Ask for a dense rectangle, then cut the polygon out of what comes back.

The model is never shown a silhouette and never asked to respect one. It gets a frame of
map painted edge to edge, at exactly the pixel size we want back, and the pipeline does the
cutting with a mask it already has. Geometry is then exact by construction: no rescale, no
warp, no resampling anywhere in the path.

What the warp method was quietly providing, and this has to replace, is registration --
mapping the generated outline onto the mask corrected any global shift the model applied.
Here the padding strip does that job instead, and does it as a rigid integer translation
rather than a non-rigid warp.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from ..land_fit import footprint_iou
from ..models import ContextImage
from . import prompt
from .base import (
    INPUT,
    LOCATOR,
    PADDING,
    neighbour_context,
    PlaceContext,
    Request,
    RequestContext,
    blank_canvas,
    has_padding,
)

# Beyond this fraction of the frame's shorter edge, a correlation peak is far more likely to
# be a mis-registration than a real shift. Falling back to no correction is safe; applying a
# wrong shift confidently is not.
MAX_DRIFT_FRACTION = 0.05


def build_prompt(
    style_prompt: str,
    context: list[ContextImage],
    pad_box: tuple[int, int, int, int] | None = None,
    frame_size: tuple[int, int] | None = None,
) -> str:
    """Full-frame repaint, as the list of paragraphs that apply. No silhouette language.

    The position instruction is load-bearing rather than decorative: the pipeline pastes the
    return back at a fixed offset and cuts a fixed polygon out of it, so a model that
    recomposes produces terrain out of register with the padding beside it.
    """
    has_pad = any(item.role == "padding" for item in context)
    rect = ""
    if pad_box:
        x0, y0, x1, y1 = pad_box
        rect = f" ({x0}, {y0}) to ({x1}, {y1})"

    if not has_pad:
        return prompt.assemble(context, prompt.REDRAW_THE_FRAME, prompt.text(style_prompt))
    return prompt.assemble(
        context,
        prompt.padding_rectangle(rect.strip(), frame_size) if rect and frame_size else None,
        prompt.REDRAW_THE_FRAME,
        prompt.padding_is_fixed(rect),
        prompt.PADDING_SETS_THE_STYLE,
        prompt.NEIGHBOURS_ARE_CONTEXT,
        prompt.ONE_PICTURE,
        prompt.ABSORB_THE_CORRECTION_INWARD,
        prompt.reminder_padding_pixel_perfect(rect),
    )


def _gradient(image: Image.Image) -> np.ndarray:
    """Gradient magnitude, as float32.

    Correlating on gradients rather than raw luma means a strip the model has restyled --
    different hue, different contrast -- still registers on the forms that did not move.
    """
    grey = np.asarray(image.convert("L"), dtype=np.float32)
    dx = cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(dx, dy)


def measure_drift(
    sent: Image.Image,
    returned: Image.Image,
    padding_mask: Image.Image,
) -> tuple[tuple[int, int], dict]:
    """How far the content of ``returned`` has moved from where it sat in ``sent``.

    Positive means right and down. Correcting is applying the negative of it.

    The padding strip is the reference because it is the one region whose correct contents
    are known exactly -- we sent them. A level with no padding is the first accepted, so
    nothing has been drawn for it to line up with and no correction is needed or possible.
    """
    info: dict = {"drift_px": [0, 0], "drift_applied": False}
    box = padding_mask.convert("L").getbbox()
    if box is None:
        info["drift_reason"] = "no padding to register against"
        return (0, 0), info

    sent_patch, returned_patch = _gradient(sent.crop(box)), _gradient(returned.crop(box))
    if min(sent_patch.shape) < 8:
        info["drift_reason"] = "padding region too small to register"
        return (0, 0), info

    (shift_x, shift_y), response = cv2.phaseCorrelate(sent_patch, returned_patch)
    dx, dy = int(round(shift_x)), int(round(shift_y))
    info["drift_px"] = [dx, dy]
    info["drift_response"] = round(float(response), 4)

    limit = max(1, int(min(sent.size) * MAX_DRIFT_FRACTION))
    if max(abs(dx), abs(dy)) > limit:
        info["drift_reason"] = f"estimate {dx},{dy} exceeds the {limit}px sanity limit"
        return (0, 0), info
    info["drift_applied"] = bool(dx or dy)
    return (dx, dy), info


def shift_image(image: Image.Image, dx: int, dy: int) -> Image.Image:
    """Move the content right by ``dx`` and down by ``dy``, in whole pixels.

    Lossless where it matters: no resampling, so nothing is squashed or softened. Edge
    replication rather than a fill because the polygon can sit close to the frame border,
    and pulling ``outside_color`` into it would punch a hole in the art.
    """
    if not dx and not dy:
        return image
    pixels = np.asarray(image.convert("RGBA"))
    pad_x, pad_y = abs(dx), abs(dy)
    padded = np.pad(pixels, ((pad_y, pad_y), (pad_x, pad_x), (0, 0)), mode="edge")
    top, left = pad_y - dy, pad_x - dx
    cropped = padded[top : top + pixels.shape[0], left : left + pixels.shape[1]]
    return Image.fromarray(cropped, mode="RGBA")


class FrameRenderer:
    name = "frame"

    def preflight(self, ctx: RequestContext) -> None:
        """Nothing to refuse: this method cuts the polygon itself and never needs the
        model to leave black, so a polygon filling the canvas is fine here."""

    def request(self, ctx: RequestContext) -> Request:
        box = ctx.frame.box
        roster: list[tuple[ContextImage, Image.Image]] = [(INPUT, ctx.generation_input.crop(box))]
        if has_padding(ctx.locked_mask):
            roster.append((PADDING, ctx.locked_pixels.crop(box)))
        roster.append((LOCATOR, ctx.locator))
        for level_id, status, image, direction in ctx.neighbours:
            roster.append((neighbour_context(level_id, status, direction), image))

        context = [item for item, _ in roster]
        pad_box = None
        if has_padding(ctx.locked_mask):
            bbox = ctx.locked_mask.crop(box).getbbox()      # padding rect in frame pixels
            if bbox:
                pad_box = (bbox[0], bbox[1], bbox[2] - 1, bbox[3] - 1)
        return Request(
            images=tuple(roster),
            prompt=build_prompt(ctx.style_prompt, context, pad_box, ctx.frame.size),
            size=ctx.frame.size,
        )

    def place(self, returned: Image.Image, ctx: PlaceContext) -> tuple[Image.Image, dict]:
        # No warp stands behind this to rescue a wrong size, so a mismatch is fatal rather
        # than something to resize away. In practice it means the provider or the size config
        # is wrong for this run, not that a draw came back oddly.
        if returned.size != ctx.frame.size:
            raise ValueError(
                f"generated image is {returned.size}, expected the frame size {ctx.frame.size}; "
                f"the provider returned a different size than was requested"
            )

        box = ctx.frame.box
        (dx, dy), info = measure_drift(ctx.sent_input, returned, ctx.locked_mask.crop(box))
        # Undo the measured displacement: a rigid integer translation, which is what the warp
        # was achieving as a side effect of outline-matching, without the warp's distortion.
        registered = shift_image(returned.convert("RGBA"), -dx, -dy)

        canvas = blank_canvas(ctx)
        canvas.paste(registered, (ctx.frame.left, ctx.frame.top))
        normalized = Image.composite(canvas, blank_canvas(ctx), ctx.generation_mask)

        # Recorded, not gated: with no silhouette to reproduce there is nothing for this to
        # reject, but it stays comparable against the warp path on the same level.
        info["footprint_iou_raw"] = round(footprint_iou(normalized, ctx.generation_mask), 4)
        info["footprint_iou"] = info["footprint_iou_raw"]
        info["rescale_applied"] = False
        return normalized, info
