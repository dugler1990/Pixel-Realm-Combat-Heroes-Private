"""The one seam between the pipeline and the model.

Everything geometric -- the canvas, the coordinate system, the polygon masks, overlap
computation, the padding claim logic, the hard paste, accept, propagate, validate -- is the
same whichever way a level is drawn. What varies is only three things, and all three are
about talking to the model: what image it is shown, what it is told, and how the return
becomes a canvas-sized layer.

So a renderer owns exactly that, canvas in and canvas out. No other module in the pipeline
names a rendering method; the single conditional lives in ``get_renderer``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image

from ..frames import Frame
from ..models import ContextImage


class PreflightRejected(ValueError):
    """The generation is certain to be rejected, and that was knowable before paying for it.

    ``is_full_bleed`` throws out a return with no black left in it, because the warp then
    traces the canvas rectangle as if it were a coastline. When the polygon already fills the
    canvas, the model has no black to leave -- the rejection is guaranteed, not likely.
    """

    def __init__(self, message: str, *, reason: str, coverage: float):
        super().__init__(message)
        self.reason = reason
        self.coverage = coverage


# Leaving less black than is_full_bleed's 2% floor. Checked against the mask, which exists
# long before the call does.
MAX_POLYGON_COVERAGE = 0.98


def check_coverage(generation_mask, level_id: str) -> None:
    coverage = float((np.asarray(generation_mask.convert("L")) > 0).mean())
    if coverage > MAX_POLYGON_COVERAGE:
        raise PreflightRejected(
            f"level {level_id} cannot be generated with the warp renderer: its polygon covers "
            f"{coverage:.1%} of the canvas, leaving under {(1 - MAX_POLYGON_COVERAGE):.0%} "
            f"black. The warp needs black around the art to find its outline, so whatever "
            f"comes back is rejected as full bleed. Use the frame renderer for this level, or "
            f"give it a smaller polygon on a larger canvas.",
            reason="no_margin",
            coverage=coverage,
        )


class FootprintRejected(ValueError):
    """The raw generation did not paint the supplied silhouette closely enough."""

    def __init__(
        self,
        message: str,
        *,
        footprint_iou: float,
        threshold: float,
        reason: str = "footprint",
    ):
        super().__init__(message)
        self.footprint_iou = footprint_iou
        self.threshold = threshold
        self.reason = reason


@dataclass(frozen=True)
class Request:
    """What to send: images in roster order, the text, and the size to ask for.

    ``images`` carries the roster and the pixels together so the prompt numbering and the
    pictures that arrive cannot drift apart -- they are produced by one function.
    """

    images: tuple[tuple[ContextImage, Image.Image], ...]
    prompt: str
    size: tuple[int, int]


@dataclass(frozen=True)
class RequestContext:
    """Canvas-space inputs available when building a request."""

    level_id: str
    canvas_size: tuple[int, int]
    frame: Frame
    outside_color: tuple[int, int, int, int]
    generation_input: Image.Image
    generation_mask: Image.Image
    locked_pixels: Image.Image
    locked_mask: Image.Image
    locator: Image.Image
    style_prompt: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)
    refine: bool = False
    # True when the polygon goes as the API's mask. Both of this renderer's guards -- the
    # coverage preflight and the full-bleed rejection -- exist for one reason: the warp had to
    # recover the outline from the returned pixels, so a render with no black left was
    # unusable. Under the mask nothing is recovered; the polygon is known independently. Six
    # levels here have polygons covering 98.8-99.1% of their canvas, and a correct render of
    # those legitimately leaves almost no black. Guarding them then throws away the right
    # answer.
    mask_holds_the_shape: bool = False
    # Send ONLY the terrain image plus the API mask -- no silhouette, locator or neighbours.
    # Four images with a correct mask came back 100% painted on level 01 of the 7x6 run; one
    # image with the same mask lands on the polygon.
    single_image: bool = False
    # The complete adjacent levels the padding strip is cut from: (level_id, status, image),
    # status being "finished" for accepted art or "rough" for the un-generated template. A
    # 150px strip on its own gives the model no idea what it belongs to.
    neighbours: tuple[tuple[str, str, Image.Image, str], ...] = ()


@dataclass(frozen=True)
class PlaceContext:
    """Job-space inputs available when normalizing a return.

    Everything here comes from the job snapshot rather than the level directory, so a
    generation is always normalized against the exact bytes it was made from.
    """

    level_id: str
    canvas_size: tuple[int, int]
    frame: Frame
    outside_color: tuple[int, int, int, int]
    generation_mask: Image.Image
    locked_mask: Image.Image
    sent_input: Image.Image
    rescale_below_iou: float = 0.0
    # Off by default. The warp forces the outline onto the mask by deforming the whole
    # picture, which shifts every feature in it -- including the padding strips other
    # levels will inherit. A raw score is reported instead, so a bad draw is retried
    # rather than stretched into place.
    fit_to_mask: bool = False
    # Trim the spill at the polygon instead. Nothing moves, so unlike the warp it is safe on
    # art other levels inherit -- but it cannot fill a shortfall. Right when ``cut_iou`` is
    # near 1 and the raw IoU is not, which is the normal shape of the error now the API mask
    # is sent correctly. Ignored when fit_to_mask is on: the warp already lands on the mask.
    cut_to_mask: bool = False
    # See RequestContext.mask_holds_the_shape: with the polygon known from the mask,
    # a full-bleed return has nothing to be rejected for -- unless the warp is on,
    # which does still trace the outline out of the pixels.
    mask_holds_the_shape: bool = False


class Renderer(Protocol):
    name: str

    def preflight(self, ctx: RequestContext) -> None:
        """Raise PreflightRejected if this level cannot possibly be placed."""

    def request(self, ctx: RequestContext) -> Request:
        """Images, prompt and requested size for one generation."""

    def place(self, returned: Image.Image, ctx: PlaceContext) -> tuple[Image.Image, dict]:
        """A canvas-sized RGBA ready for the padding paste, plus fields for ``job.json``."""


# The shared vocabulary of reference images. Each renderer picks the ones its method needs;
# the descriptions are what the model reads, numbered by position in the roster it is given.
INPUT = ContextImage(
    "input.png",
    "terrain",
    "the terrain to redraw at high quality, with the finished padding already in place",
)
SILHOUETTE = ContextImage(
    "generation_mask.png",
    "silhouette",
    "the exact shape to fill: paint only inside the white area, everything outside it stays black",
)
PADDING = ContextImage(
    "locked_overlap.png",
    "padding",
    "that padding on its own, at its exact position, everything else blank",
)
def neighbour_context(level_id: str, status: str, direction: str = "") -> ContextImage:
    where = f" lying to the {direction} of this one" if direction else ""
    return ContextImage(
        f"neighbor_{level_id}.png",
        "neighbour",
        f"the complete neighbouring level {level_id}{where} ({status} art); the padding is cut "
        f"from it, and it is context only - do not copy it into this frame",
    )


# Only present on a retry. It is the one image the model made itself, so it is named as
# such -- "your previous attempt" is what makes the criticism that follows land on it.
def retry_context(attempt: int, ordinal: str) -> ContextImage:
    """One rejected attempt. Numbered so the criticism of each can name its own picture."""
    return ContextImage(
        f"previous_attempt_{attempt:03d}.png",
        "retry",
        f"your {ordinal} attempt at this piece, which was rejected",
    )


def annotation_context(filename: str, note: str) -> ContextImage:
    """An image attached by hand to one retry, described by whatever was said about it.

    The note is the whole description: an attachment is only worth sending if the person
    sending it can say what it shows and what to do about it.
    """
    return ContextImage(filename, "annotation", note)


LOCATOR = ContextImage(
    "locator.png",
    "locator",
    "where this piece sits on the world map, for orientation only, do not copy from it",
)


def roster_lines(context: list[ContextImage]) -> list[str]:
    """The numbered list that opens a prompt.

    Generated from the same roster the client sends, so the numbering in the text and the
    pictures that arrive cannot disagree.
    """
    lines = [f"Image {index} is {item.description}." for index, item in enumerate(context, start=1)]
    return lines + [""] if lines else lines


def blank_canvas(ctx: RequestContext | PlaceContext) -> Image.Image:
    return Image.new("RGBA", ctx.canvas_size, ctx.outside_color)


def has_padding(locked_mask: Image.Image) -> bool:
    """Whether this level copies anything from a neighbour.

    A seed level has no padding, so the padding image drops out of the roster and the prompt
    numbering closes up. That is why the prompt is generated from the roster rather than
    written with fixed numbers.
    """
    return bool(locked_mask.convert("L").getbbox())


def ascii_prompt(lines: list[str]) -> str:
    """Join and hard-fail on any non-ASCII character.

    A non-ASCII character near the start of a prompt has landed in a provider's returned
    filename before now, and the download URL then could not be requested at all -- after
    the image had been generated and billed.
    """
    prompt = "\n".join(lines).strip() + "\n"
    if not prompt.isascii():
        offender = next(character for character in prompt if not character.isascii())
        raise ValueError(f"prompt contains the non-ASCII character {offender!r}")
    return prompt


def load_image(path: Path, mode: str = "RGBA") -> Image.Image:
    with Image.open(path) as opened:
        return opened.convert(mode)
