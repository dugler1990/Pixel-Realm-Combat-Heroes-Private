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

from ..land_fit import (
    cut_to_mask,
    fit_generated_to_mask,
    footprint_iou,
    is_full_bleed,
    rescale_to_mask,
)
from ..models import ContextImage
from . import prompt
from .base import (
    INPUT,
    LOCATOR,
    PADDING,
    FootprintRejected,
    PlaceContext,
    Request,
    RequestContext,
    check_coverage,
    neighbour_context,
    blank_canvas,
    has_padding,
)


def build_prompt(style_prompt: str, context: list[ContextImage],
                 single_image: bool = False, padding_at: str | None = None) -> str:
    """The generation prompt, as the list of paragraphs that apply.

    The images are the control mechanism, not the wording. Kept deliberately short:
    constraints that outnumber the instruction drown it, and a level name like "Bitter Floe
    Coast" reads as a subject to invent rather than a chunk to repaint, so no name appears.
    """
    def index_of(role: str) -> int | None:
        return next((n for n, item in enumerate(context, start=1) if item.role == role), None)

    if single_image:
        # Empty context on purpose: with one image there is no roster to number, and a line
        # saying "image 1 is..." only invites the model to look for an image 2.
        if padding_at is None:
            return prompt.assemble(
                [],
                prompt.SINGLE_IMAGE_REDRAW,
                prompt.NOTHING_MOVES,
                prompt.text(style_prompt),
            )
        # Style before the padding rules, never after: the join rule is the one thing allowed
        # to override a position, so nothing may follow it and contradict it. The style
        # prompt's "Preserve the layout exactly" is dropped here for exactly that reason.
        return prompt.assemble(
            [],
            prompt.SINGLE_IMAGE_REDRAW,
            prompt.text(prompt.without_layout_clause(style_prompt)),
            prompt.single_image_padding(padding_at),
        )

    padding_index = index_of("padding")
    if padding_index is None:
        return prompt.assemble(
            context,
            prompt.ONLY_IMAGE_ONE_IS_DRAWN,
            prompt.REDRAW_AT_QUALITY,
            prompt.text(style_prompt),
        )
    return prompt.assemble(
        context,
        prompt.ONLY_IMAGE_ONE_IS_DRAWN,
        prompt.piece_of_a_larger_map(padding_index),
        prompt.MATCH_THE_FINISHED_PART,
        prompt.KEEP_EVERYTHING_IN_PLACE,
        prompt.REMINDER_PADDING_ONLY,
    )


def build_refine_prompt(context: list[ContextImage]) -> str:
    """Second pass over already-finished art: align it to the padding, nothing else.

    The level's own image already contains the padding hard-pasted, so the model cannot tell
    which region is authoritative from it alone -- that comes from the padding being its own
    numbered image in the roster.
    """
    return prompt.assemble(context, prompt.REFINE_ALIGN_TO_THE_PADDING, footer=False)


class WarpRenderer:
    name = "warp"

    def preflight(self, ctx: RequestContext) -> None:
        if ctx.mask_holds_the_shape:
            # Nothing to protect: the outline is the mask, not something read back out of
            # the render, so a polygon that fills the canvas is fine.
            return
        check_coverage(ctx.generation_mask, ctx.level_id)

    def request(self, ctx: RequestContext) -> Request:
        # Masking the input to the polygon belongs here rather than upstream: it is this
        # method's way of presenting a level, not a property of the level. The canonical
        # generation_input.png stays dense so the frame renderer can crop it.
        masked = Image.composite(ctx.generation_input, blank_canvas(ctx), ctx.generation_mask)

        # The silhouette used to ride here as a reference image. It does not any more: the
        # same polygon goes as the API's mask, and the two were bitwise identical, so it was
        # showing the model the shape twice. The mask is what actually holds it -- 0.970 IoU
        # against 0.305 when the alpha polarity was wrong.
        roster: list[tuple[ContextImage, Image.Image]] = [(INPUT, masked)]
        if ctx.single_image:
            # Everything the roster carried is either already in image 1 (the padding is
            # pasted into it) or is context the mask makes unnecessary.
            context = [INPUT]
            return Request(
                images=((INPUT, masked),),
                prompt=build_prompt(ctx.style_prompt, context, single_image=True,
                                    padding_at=prompt.describe_padding(ctx.locked_mask)),
                size=ctx.canvas_size,
            )
        if has_padding(ctx.locked_mask):
            roster.append((PADDING, ctx.locked_pixels))
        roster.append((LOCATOR, ctx.locator))
        # job_builder loads these for every level regardless of renderer; the frame method
        # already uses them. A 150px strip on its own says nothing about what it is part of.
        for level_id, status, image, direction in ctx.neighbours:
            roster.append((neighbour_context(level_id, status, direction), image))

        context = [item for item, _ in roster]
        # Not named `prompt`: that shadows the module for the whole method, and the
        # single-image branch above calls prompt.describe_padding before this line runs.
        text = (
            build_refine_prompt(context)
            if ctx.refine
            else build_prompt(ctx.style_prompt, context)
        )
        return Request(images=tuple(roster), prompt=text, size=ctx.canvas_size)

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

        if is_full_bleed(returned) and not (ctx.mask_holds_the_shape and not ctx.fit_to_mask):
            # The only unrecoverable case: no black left to define an outline, so rescaling is
            # a no-op and the warp traces the canvas rectangle as if it were a coastline.
            raise FootprintRejected(
                f"generated image is full bleed (footprint IoU {raw_iou:.3f}): it has no "
                f"usable land outline, so it cannot be rescaled or warped",
                footprint_iou=raw_iou,
                threshold=ctx.rescale_below_iou,
                reason="full_bleed",
            )

        if not ctx.fit_to_mask:
            info["fit_to_mask"] = False
            if ctx.cut_to_mask:
                # Trim the spill. Worth doing only because the error is now a fringe: with the
                # API mask sent at the polarity the model obeys, 95% of the disagreement on
                # level 02 sat within 25px of the boundary. Cutting a fringe costs nothing;
                # cutting a genuinely misplaced render would amputate real art, which is why
                # this is a decision made per attempt against cut_iou rather than a default.
                cut = cut_to_mask(
                    returned, ctx.generation_mask, outside_color=ctx.outside_color
                )
                info["cut_to_mask"] = True
                info["footprint_iou"] = round(footprint_iou(cut, ctx.generation_mask), 4)
                return cut, info
            # Otherwise return exactly what came back; where two levels overlap, core
            # ownership decides at assembly.
            info["footprint_iou"] = round(raw_iou, 4)
            info["cut_to_mask"] = False
            return returned.convert("RGBA"), info

        info["fit_to_mask"] = True
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
