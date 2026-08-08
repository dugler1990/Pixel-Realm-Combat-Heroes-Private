"""Ask for the polygon on a black canvas, then correct the geometry that comes back.

The original method. The model is shown the level's silhouette against black and asked to
reproduce it; it never does exactly, so the return is squashed onto the template bounding
box when the footprint is bad enough and then thin-plate-spline warped so its outline lands
on the mask. That corrects translation and scale as a side effect -- and distorts the
artwork, which is why the frame renderer exists.

Kept working and unchanged so it stays available as a fallback and as a comparison.
"""

from __future__ import annotations

from PIL import Image

from ..land_fit import fit_generated_to_mask, footprint_iou, is_full_bleed, rescale_to_mask
from ..models import ContextImage
from .base import (
    INPUT,
    LOCATOR,
    PADDING,
    SILHOUETTE,
    FootprintRejected,
    PlaceContext,
    Request,
    RequestContext,
    ascii_prompt,
    blank_canvas,
    has_padding,
    roster_lines,
)


def build_prompt(style_prompt: str, context: list[ContextImage]) -> str:
    """The generation prompt.

    The images are the control mechanism, not the wording. Kept deliberately short:
    constraints that outnumber the instruction drown it, and a level name like "Bitter Floe
    Coast" reads as a subject to invent rather than a chunk to repaint, so no name appears.
    """
    has_pad = any(item.role == "padding" for item in context)
    lines = roster_lines(context)
    lines.extend(
        [
            "Redraw image 1 at high finished quality.",
            "It is a low resolution upscale: soft, blurred, washed out. Redraw it sharp and",
            "detailed, with strong contrast and clear painted form. Nothing moves, nothing is",
            "added, nothing is removed, nothing changes what it is. Quality only.",
            "",
        ]
    )
    if has_pad:
        lines.extend(
            [
                "The already-finished art is the standard to reach: its sharpness, its brush",
                "treatment, its contrast, its lighting. Carry that outward across the rest of",
                "the image so the whole thing reads as one painting, with nothing marking where",
                "the finished part ends. Terrain type does not change, only how it is rendered.",
                "",
            ]
        )
    elif style_prompt:
        lines.extend([style_prompt, ""])
    lines.append("Top-down, even lighting, no cast shadows. No text or labels.")
    return ascii_prompt(lines)


def build_refine_prompt(context: list[ContextImage]) -> str:
    """Second pass over already-finished art: align it to the padding, nothing else.

    The level's own image already contains the padding hard-pasted, so the model cannot tell
    which region is authoritative from it alone -- that comes from the padding being its own
    numbered image in the roster.
    """
    lines = roster_lines(context)
    lines.extend(
        [
            "Image 1 is already a finished painting.",
            "Part of it was carried over from the neighbouring level and is already correct.",
            "That carried-over part is the source of truth for hue, contrast, texture scale",
            "and brushwork. Bring the rest of image 1 into line with it so the whole thing",
            "reads as one painting.",
            "",
            "Do not change what anything is or where it sits. Do not add or remove anything.",
            "No text or labels.",
        ]
    )
    return ascii_prompt(lines)


class WarpRenderer:
    name = "warp"

    def request(self, ctx: RequestContext) -> Request:
        # Masking the input to the polygon belongs here rather than upstream: it is this
        # method's way of presenting a level, not a property of the level. The canonical
        # generation_input.png stays dense so the frame renderer can crop it.
        masked = Image.composite(ctx.generation_input, blank_canvas(ctx), ctx.generation_mask)

        roster: list[tuple[ContextImage, Image.Image]] = [
            (INPUT, masked),
            # Kept in its native "L" mode: the job snapshot doubles as the canvas-space mask
            # the ingest path reads back.
            (SILHOUETTE, ctx.generation_mask),
        ]
        if has_padding(ctx.locked_mask):
            roster.append((PADDING, ctx.locked_pixels))
        roster.append((LOCATOR, ctx.locator))

        context = [item for item, _ in roster]
        prompt = build_refine_prompt(context) if ctx.refine else build_prompt(ctx.style_prompt, context)
        return Request(images=tuple(roster), prompt=prompt, size=ctx.canvas_size)

    def place(self, returned: Image.Image, ctx: PlaceContext) -> tuple[Image.Image, dict]:
        if returned.size != ctx.canvas_size:
            raise ValueError(f"generated image is {returned.size}, expected {ctx.canvas_size}")

        # Score the RAW generation before the warp. fit_generated_to_mask will happily squash
        # a reframed render onto the silhouette, so without this the shape error is invisible
        # downstream.
        raw_iou = footprint_iou(returned, ctx.generation_mask)
        info: dict = {
            "footprint_iou_raw": round(raw_iou, 4),
            "rescale_below_iou": ctx.rescale_below_iou,
            "rescale_applied": False,
        }

        if is_full_bleed(returned):
            # The only unrecoverable case: no black left to define an outline, so rescaling is
            # a no-op and the warp traces the canvas rectangle as if it were a coastline.
            raise FootprintRejected(
                f"generated image is full bleed (footprint IoU {raw_iou:.3f}): it has no "
                f"usable land outline, so it cannot be rescaled or warped",
                footprint_iou=raw_iou,
                threshold=ctx.rescale_below_iou,
                reason="full_bleed",
            )

        final_iou = raw_iou
        if raw_iou < ctx.rescale_below_iou:
            # Reframed: squash it back onto the template bbox, which is known exactly from the
            # mask. Whatever comes out goes to the warp -- shape is scored, not judged.
            returned, rescale_info = rescale_to_mask(
                returned, ctx.generation_mask, outside_color=ctx.outside_color
            )
            final_iou = footprint_iou(returned, ctx.generation_mask)
            info["rescale_applied"] = True
            info.update(rescale_info)
        info["footprint_iou"] = round(final_iou, 4)

        normalized = fit_generated_to_mask(
            returned, ctx.generation_mask, outside_color=ctx.outside_color
        )
        return normalized, info
