"""The paragraphs a generation prompt is made of, and the one function that assembles them.

Both renderers used to build their text with nested conditions and the wording typed inline in
each branch. That is how a paragraph ended up in the padded case and not the unpadded one, and
how a sentence went on naming "image 3" after the roster had renumbered.

So the paragraphs are named values here, and a prompt is a list of them. Whether a block
applies is then one line to read rather than three branches deep, and adding a rule is adding a
row rather than finding every branch it belongs in.

A block is a list of lines, or ``None`` when it does not apply. ``assemble`` drops the Nones,
so a caller can write the condition inline and the shape of the whole prompt stays visible.
"""

from __future__ import annotations

from ..models import ContextImage
from .base import ascii_prompt, roster_lines

Block = list[str] | None

FOOTER = "Top-down, even lighting, no cast shadows. No text or labels."


def assemble(context: list[ContextImage], *blocks: Block, footer: bool = True) -> str:
    """Roster, then each block that applies, then the footer.

    The refine pass opts out: it is a second look at finished art, not a fresh painting, and
    restating the rendering style there would invite it repainting rather than aligning.
    """
    lines = roster_lines(context)
    for block in blocks:
        if block:
            lines.extend(block)
            lines.append("")
    if footer:
        lines.append(FOOTER)
    return ascii_prompt(lines)


def text(value: str) -> Block:
    """A caller-supplied paragraph -- a style prompt -- as a block."""
    return [value] if value else None


# --- what the piece is -------------------------------------------------------------------

# Attempt 12 returned the locator: the whole region, river, pyramids and all, at 0.80 IoU
# against image 3 and 0.43 against image 1. Every other image had been described as context
# in its own roster line, but nothing anywhere said which image was the one being drawn, and
# the only picture in the set that looked like a finished map was the locator.
ONLY_IMAGE_ONE_IS_DRAWN: Block = [
    "Only image 1 is drawn. Every other image is reference material, there to help you",
    "draw image 1 the way it is wanted - none of them is the picture to return, and",
    "nothing from any of them appears in your output unless image 1 already has it.",
]


def piece_of_a_larger_map(padding_index: int) -> Block:
    """Numbered from the roster, never hardcoded: dropping an image renumbers the rest."""
    return [
        "This is one piece of a larger map. Part of image 1 is already finished: it",
        f"was painted as the neighbouring piece, and image {padding_index} shows that",
        "part on its own. It gets put back exactly as it is, so nothing you do to it",
        "survives.",
    ]


REDRAW_AT_QUALITY: Block = [
    "Redraw image 1 at high finished quality.",
    "It is a low resolution upscale: soft, blurred, washed out. Redraw it sharp and",
    "detailed, with strong contrast and clear painted form. Nothing moves, nothing is",
    "added, nothing is removed, nothing changes what it is. Quality only.",
]

REDRAW_THE_FRAME: Block = [
    "Redraw image 1 at high finished quality.",
    "It is a low resolution upscale: soft, blurred, washed out. Redraw it sharp and",
    "detailed, with strong contrast and clear painted form. Quality only.",
    "",
    "Paint the whole image, edge to edge, with no border and no empty space.",
    "Every feature stays at exactly the same position and the same size as in image 1.",
    "Nothing moves, nothing is added, nothing is removed, nothing is recentred,",
    "nothing changes what it is.",
]

# --- the single-image form ----------------------------------------------------------------
#
# One image and the API mask, nothing else. Measured on level 01 of the 7x6 run: the same
# prompt and mask with four images came back 100% painted, mask ignored; with one image it
# lands on the polygon.
#
# The padded and unpadded forms say OPPOSITE things about position, so they cannot share a
# paragraph. With no padding nothing may move at all. With padding the strip is pasted back
# byte-identical afterwards, so anything the model reconciled on that side is thrown away and
# returns as a seam -- the rest of the image is the only side that can give.

SINGLE_IMAGE_REDRAW: Block = [
    "Redraw this image at high finished quality.",
    "It is a low resolution upscale: soft, blurred, washed out. Redraw it sharp and",
    "detailed, with strong contrast and clear painted form. Quality only.",
]

# Only when there is no padding. Nothing here may be softened: there is no join to reconcile,
# so any licence to move something is licence to introduce an error.
NOTHING_MOVES: Block = [
    "The position and size of everything must be exactly the same.",
    "Every feature stays exactly where it is, at exactly the size it is. Nothing moves,",
    "nothing is added, nothing is removed, nothing becomes something else.",
]

# Sides whose bounding box reaches within this fraction of the canvas count as touching it.
_EDGE_TOLERANCE = 0.005
# Beyond this the region is not a strip along an edge and describing it as one would mislead.
_MAX_STRIP = 0.5


def describe_padding(locked_mask) -> str | None:
    """Where the padding sits, in words the model can act on.

    In the single-image form the padding is not its own picture any more -- it is a region
    inside the one image -- so nothing identifies it unless the prompt does. It is named twice
    over, by position here and by appearance in the paragraph, because either alone is a guess.

    Returns None when there is no padding at all.
    """
    import numpy as np

    array = np.asarray(locked_mask.convert("L")) > 0
    if not array.any():
        return None
    height, width = array.shape
    ys, xs = np.where(array)
    left, right, top, bottom = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    near_x, near_y = max(8, int(_EDGE_TOLERANCE * width)), max(8, int(_EDGE_TOLERANCE * height))
    across, down = (right - left + 1) / width, (bottom - top + 1) / height

    sides: list[str] = []
    if left <= near_x and across < _MAX_STRIP:
        sides.append(f"the left {round(across * 100)}%")
    if right >= width - 1 - near_x and across < _MAX_STRIP:
        sides.append(f"the right {round(across * 100)}%")
    if top <= near_y and down < _MAX_STRIP:
        sides.append(f"the top {round(down * 100)}%")
    if bottom >= height - 1 - near_y and down < _MAX_STRIP:
        sides.append(f"the bottom {round(down * 100)}%")
    if not sides:
        return f"about {round(100 * float(array.mean()))}% of this image"
    return " and ".join(sides)


def single_image_padding(where: str) -> Block:
    """The padding rules, in three parts: what it is, match it, and the one thing that may move.

    Two names are used and only two -- "the finished art" and "the rest of the image" -- because
    the earlier wording called the same region three different things in four paragraphs.
    """
    return [
        f"{where[0].upper()}{where[1:]} of this image is finished art from the neighbouring",
        "piece. You can see it clearly: it is the sharp, high resolution part, while the",
        "rest of the image is soft. Return the finished art unchanged - same pixels, same",
        "place, same size.",
        "",
        "Paint the rest of the image to match the finished art exactly - same colours,",
        "brightness, contrast, brush treatment and detail size - so the frame reads as one",
        "painting with no visible join.",
        "",
        "Keep everything in the rest of the image where it is. The one exception is at the",
        "border with the finished art: where something is split across it and the two halves",
        "do not line up - half a rock in the finished art, half in the rest of the image,",
        "offset from each other - move the half in the rest of the image so it sits exactly",
        "with the half in the finished art. Never move the finished art.",
    ]


# The style prompt is the caller's, and it ends with an absolute the padded form contradicts.
_LAYOUT_CLAUSE = "Preserve the layout exactly; "


def without_layout_clause(style_prompt: str) -> str:
    """The style prompt minus "Preserve the layout exactly;".

    Dropped here rather than in the config so the unpadded form keeps it -- there it is
    correct and wanted. Left in alongside the padded form it is the last word on position and
    overrides the permission to line a split feature up across the join.
    """
    trimmed = style_prompt.replace(_LAYOUT_CLAUSE, "").replace(_LAYOUT_CLAUSE.strip(), "")
    # Removing a clause mid-sentence leaves the next word lowercase after a full stop.
    out, capitalise = [], False
    for index, part in enumerate(trimmed):
        if capitalise and part.isalpha():
            out.append(part.upper())
            capitalise = False
        else:
            out.append(part)
            if part == ".":
                capitalise = True
    return "".join(out).strip()


# --- the padding -------------------------------------------------------------------------

MATCH_THE_FINISHED_PART: Block = [
    "Your job is the rest. Image 1 is a soft, blurred, washed out upscale, so redraw",
    "it sharp and detailed - and match the finished part exactly: its colours, its",
    "brightness, its contrast, its brush treatment, the size of its detail. The two",
    "must read as one painting, with nothing marking where one ends and the other",
    "begins.",
]

KEEP_EVERYTHING_IN_PLACE: Block = [
    "Keep everything exactly where image 1 puts it and at the same size. Nothing is",
    "added, nothing is removed, nothing becomes something else - resolution only.",
    "The one exception is the join: a road, track, ridge or crack that arrives",
    "offset must be bent so it runs straight through - and bend it out in the",
    "middle, away from the join, never at the edge itself.",
]


def padding_rectangle(rect: str, frame_size: tuple[int, int]) -> Block:
    """Where the strip actually is. The padding image is a full frame blank but for the
    strip, so without coordinates the model has to guess the region it must not touch."""
    return [f"The padding occupies the rectangle from {rect} in this "
            f"{frame_size[0]}x{frame_size[1]} image."]


def padding_is_fixed(rect: str) -> Block:
    return [
        f"The padding{rect} is fixed. Return it pixel for pixel identical to image 2:",
        "same colours, same detail, same position, same size. Do not repaint it,",
        "resharpen it, restyle it or shift it.",
    ]


PADDING_SETS_THE_STYLE: Block = [
    "Everything outside the padding is yours to redraw, and the padding decides how",
    "it looks: take its colours, brightness, contrast, grain and brush treatment and",
    "carry them across the whole frame. Do not change what any object is, only how",
    "it is rendered.",
]

NEIGHBOURS_ARE_CONTEXT: Block = [
    "The later images are the complete neighbouring levels, shown whole: the padding",
    "is a strip cut out of them. Use them to see what the padding is part of and how",
    "the terrain continues past this frame. Do not copy them in - only image 1's",
    "layout is drawn here.",
]

ONE_PICTURE: Block = [
    "The two parts must become one picture. Where your work meets the padding the",
    "change must be invisible: no line, no step in colour or brightness, no shift in",
    "texture. The finished frame is a single continuous composition, not a strip",
    "joined onto a painting.",
]

# The padding is pasted back byte-identical, so a mismatch reconciled on that side is
# discarded and returns as a seam. The join is the one place that cannot absorb a correction.
ABSORB_THE_CORRECTION_INWARD: Block = [
    "Where a feature does not line up across the join, change the rest of the image",
    "to meet it: hold the join itself exact and absorb the difference gradually as",
    "you work inward, so the correction is spread across the middle of the frame",
    "instead of piled up at the edge.",
]

# The outline is not argued for any more. It used to be: a silhouette in the roster plus two
# paragraphs insisting the painting land on it, because nothing else held the shape. The API
# mask holds it now -- alpha 255 over the polygon, measured at 0.970 IoU against 0.305 for the
# documented polarity -- so saying it again only competes with the instructions that still
# have to land. Removed rather than left unused: an unused prompt block invites reinstating a
# constraint whose job is already done.

# --- closing -------------------------------------------------------------------------------

REMINDER_PADDING_ONLY: Block = [
    "Reminder: match the finished part, and leave it untouched.",
]


# --- the refine pass ------------------------------------------------------------------------

REFINE_ALIGN_TO_THE_PADDING: Block = [
    "Image 1 is already a finished painting.",
    "Part of it was carried over from the neighbouring level and is already correct.",
    "That carried-over part is the source of truth for hue, contrast, texture scale",
    "and brushwork. Bring the rest of image 1 into line with it so the whole thing",
    "reads as one painting.",
    "",
    "Do not change what anything is or where it sits. Do not add or remove anything.",
    "No text or labels.",
]


def reminder_padding_pixel_perfect(rect: str) -> Block:
    return [f"Reminder: the padding{rect} must come back exactly pixel perfect and unchanged."]
