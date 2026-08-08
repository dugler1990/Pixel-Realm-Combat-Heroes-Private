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

from PIL import Image

from ..frames import Frame
from ..models import ContextImage


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


class Renderer(Protocol):
    name: str

    def request(self, ctx: RequestContext) -> Request:
        """Images, prompt and requested size for one generation."""

    def place(self, returned: Image.Image, ctx: PlaceContext) -> tuple[Image.Image, dict]:
        """A canvas-sized RGBA ready for the padding paste, plus fields for ``job.json``."""


# The shared vocabulary of reference images. Each renderer picks the ones its method needs;
# the descriptions are what the model reads, numbered by position in the roster it is given.
INPUT = ContextImage(
    "input.png",
    "terrain",
    "the terrain to redraw at high quality, with any already-finished areas already in place",
)
SILHOUETTE = ContextImage(
    "generation_mask.png",
    "silhouette",
    "the exact shape to fill: paint only inside the white area, everything outside it stays black",
)
PADDING = ContextImage(
    "locked_overlap.png",
    "padding",
    "the already-finished art carried over from the neighbouring level, in its exact position",
)
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
