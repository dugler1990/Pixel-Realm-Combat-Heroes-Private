"""Propose the sub-regions a chunk is divided into.

This is the one swappable piece of the splitter: given a chunk (its footprint polygon,
in world pixels, plus the generated chunk art) and a target count N, return N regions as
world-pixel polygons, each tagged ``flat`` or ``mountain``.

Mirrors ``image_client.make_image_client`` conventions: a factory keyed on
``config['provider']`` returns a proposer; each provider is an adapter. The default
provider ``grid`` is fully offline (no API key) so the whole splitter runs and tests end
to end without a model. A model-backed proposer (reasoned split + terrain tag) plugs in
here as a new provider with zero change to the splitter or anything downstream.

The proposer returns geometry in **world pixels**, so the splitter never has to reason
about the art/frame coordinate system.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from . import geometry
from ..openai_api import EDGE_MULTIPLE, MAX_ASPECT, MAX_EDGE, MAX_PIXELS, MIN_PIXELS, edit_image
from .masks import rasterize_polygon
from .models import Point


@dataclass(frozen=True)
class ProposedRegion:
    polygon: tuple[Point, ...]  # world pixels
    tag: str                    # "flat" | "mountain"
    name: str = ""              # optional human-readable name from the proposer


@dataclass(frozen=True)
class ProposeRequest:
    chunk_id: str
    chunk_polygon: tuple[Point, ...]  # world pixels (the chunk core polygon)
    chunk_art: Path | None            # image to reason over (chunk crop), for model proposers
    n: int
    criteria: str
    world_bbox: tuple[int, int, int, int] | None = None  # world bbox `chunk_art` maps to


class RegionProposer(ABC):
    name: str = "base"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    @abstractmethod
    def propose(self, request: ProposeRequest) -> list[ProposedRegion]:  # pragma: no cover
        ...


# --------------------------------------------------------------------------- #
# Offline default: recursive longest-axis split of the chunk footprint
# --------------------------------------------------------------------------- #
def _bisect(mask: np.ndarray) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Cut a mask across its longer axis at the median of its pixels (balances area),
    keeping the largest connected component of each half so pieces stay contiguous."""
    ys, xs = np.where(mask)
    if xs.size == 0:
        return None, None
    width = xs.max() - xs.min()
    height = ys.max() - ys.min()
    if width >= height:
        cut = int(np.median(xs))
        first = mask.copy(); first[:, cut:] = False
        second = mask.copy(); second[:, :cut] = False
    else:
        cut = int(np.median(ys))
        first = mask.copy(); first[cut:, :] = False
        second = mask.copy(); second[:cut, :] = False
    first = geometry.largest_connected_component(first)
    second = geometry.largest_connected_component(second)
    if not first.any() or not second.any():
        return None, None
    return first, second


def _split_mask(mask: np.ndarray, n: int) -> list[np.ndarray]:
    pieces: list[np.ndarray] = [mask.astype(bool)]
    while len(pieces) < n:
        index = max(range(len(pieces)), key=lambda i: int(pieces[i].sum()))
        piece = pieces.pop(index)
        first, second = _bisect(piece)
        if first is None or second is None:
            pieces.append(piece)  # cannot split further; stop growing
            break
        pieces.extend([first, second])
    return pieces


class GridRegionProposer(RegionProposer):
    """Deterministic, offline: splits the chunk footprint into N connected regions by
    recursive longest-axis cuts. Terrain-blind, so every region is tagged ``flat``. This
    is the sensible default and the test/dry-run backend; swap in a model-backed proposer
    for content-aware division + mountain tagging."""

    def propose(self, request: ProposeRequest) -> list[ProposedRegion]:
        if request.n < 1:
            raise ValueError("n must be >= 1")
        left, top, right, bottom = geometry.polygon_bbox(request.chunk_polygon)
        size = (right - left + 1, bottom - top + 1)
        local_points = tuple((x - left, y - top) for x, y in request.chunk_polygon)
        mask = np.asarray(rasterize_polygon(size, local_points)) > 0
        regions: list[ProposedRegion] = []
        for piece in _split_mask(mask, request.n):
            try:
                local_polygon = geometry.mask_to_polygon(piece, epsilon_frac=0.01)
            except ValueError:
                continue
            world_polygon = tuple((x + left, y + top) for x, y in local_polygon)
            regions.append(ProposedRegion(polygon=world_polygon, tag="flat"))
        if not regions:
            raise ValueError(f"chunk {request.chunk_id}: proposer produced no regions")
        return regions


# Distinct, well-separated colors the image model paints each region with; we trace them.
_PALETTE: tuple[tuple[int, int, int], ...] = (
    (220, 50, 50),
    (50, 200, 80),
    (60, 120, 230),
    (235, 200, 40),
    (200, 70, 210),
    (240, 140, 40),
)
_PALETTE_NAMES = ("red", "green", "blue", "yellow", "magenta", "orange")


def _valid_gen_size(width: int, height: int) -> tuple[int, int]:
    """Nearest gpt-image-2-legal size (edge multiple, pixel + aspect bounds) for the crop."""
    w, h = int(width), int(height)
    if max(w / h, h / w) > MAX_ASPECT:
        if w >= h:
            h = int(w / MAX_ASPECT) + 1
        else:
            w = int(h / MAX_ASPECT) + 1
    if max(w, h) > MAX_EDGE:
        scale = MAX_EDGE / max(w, h)
        w, h = int(w * scale), int(h * scale)
    if w * h > MAX_PIXELS:
        scale = (MAX_PIXELS / (w * h)) ** 0.5
        w, h = int(w * scale), int(h * scale)
    if w * h < MIN_PIXELS:
        scale = (MIN_PIXELS / (w * h)) ** 0.5
        w, h = int(w * scale) + 1, int(h * scale) + 1

    def up(value: int) -> int:
        return max(EDGE_MULTIPLE, ((value + EDGE_MULTIPLE - 1) // EDGE_MULTIPLE) * EDGE_MULTIPLE)

    return up(w), up(h)


def _partition_masks(painted: np.ndarray, palette, land_threshold: int = 40) -> list[np.ndarray]:
    """Partition the painted land: every non-black pixel goes to its NEAREST palette color
    (no tolerance gate), so the whole land is covered with no gaps and the masks are
    disjoint. Black background stays unassigned."""
    pixels = painted[:, :, :3].astype(np.int32)
    land = pixels.sum(axis=2) > land_threshold
    distances = np.stack(
        [((pixels - np.asarray(color, dtype=np.int32)) ** 2).sum(axis=2) for color in palette],
        axis=0,
    )
    nearest = distances.argmin(axis=0)
    return [(nearest == index) & land for index in range(len(palette))]


class ImageDivisionProposer(RegionProposer):
    """Gen-AI split, the proven way: an image model repaints the chunk into N flat-color
    sub-regions (the same idea that produced the original divisions overlay), and the
    splitter TRACES those colors into polygons -- no LLM coordinate guessing. Config
    mirrors the OpenAI image path (api_key_env, model, base_url)."""

    def _prompt(self, n: int, criteria: str) -> str:
        colors = ", ".join(_PALETTE_NAMES[:n])
        lines = [
            "This is a top-down 2.5D fantasy RPG world map. Divide the non-black land into "
            f"{n} playable areas -- each colored area becomes one game level.",
            f"Repaint every part of the land with one of exactly these {n} flat solid colors, "
            f"one color per area: {colors}.",
            "Rules:",
            "- Cover ALL the non-black land: every land pixel must be inside exactly one colored "
            "area -- no gaps, no leftover land, no overlaps. Never paint the black background.",
            "- Use SIMPLE shapes: each area is a big blocky region with a few roughly-straight "
            "edges. Do NOT trace coastlines, ridges, or bays -- cut straight across small detail.",
            "- Keep the areas roughly similar in size, but this is a SOFT preference: if the land "
            "naturally splits into (say) two large areas and one small one, that is fine.",
            "- Put boundaries where the terrain changes (mountains vs plains, a coastline), and "
            "keep a clearly mountainous zone as its own area when one stands out.",
            "- Hard edges between colors; no gradients, blending, shading, or texture.",
        ]
        if criteria.strip():
            lines.append(criteria.strip())
        return "\n".join(lines)

    def _paint(self, prompt: str, source: Path, out_path: Path, width: int, height: int) -> None:
        config = dict(self.config)
        config.setdefault("model", "gpt-image-2")
        edit_image(
            prompt=prompt,
            input_images=[Path(source)],
            mask=None,
            output_path=Path(out_path),
            width=width,
            height=height,
            config=config,
        )

    def propose(self, request: ProposeRequest) -> list[ProposedRegion]:
        if request.chunk_art is None:
            raise ValueError("image proposer requires an image (chunk_art) to paint")
        bbox = request.world_bbox or geometry.polygon_bbox(request.chunk_polygon)
        n = max(1, request.n)
        source = Path(request.chunk_art)
        painted_path = source.parent / "proposer_painted.png"
        with Image.open(source) as opened:
            gen_w, gen_h = _valid_gen_size(*opened.size)
        self._paint(self._prompt(n, request.criteria), source, painted_path, gen_w, gen_h)
        regions = self.trace(painted_path, bbox, n, source_path=source)
        if not regions:
            raise ValueError(f"{request.chunk_id}: no colored regions found in the painted image")
        return regions

    def trace(
        self,
        painted_path: Path,
        target_bbox: tuple[int, int, int, int],
        n: int,
        source_path: Path | None = None,
    ) -> list[ProposedRegion]:
        """Turn the flat-color paint into simple polygons (one per color) in the frame given
        by ``target_bbox``. If ``source_path`` (the real terrain art) is given, each region
        is tagged ``mountain`` when its terrain is markedly more rugged than the average.
        Separated from the API call so it can be re-run on an existing paint offline."""
        left, top, right, bottom = target_bbox
        span_x, span_y = max(1, right - left), max(1, bottom - top)
        painted = np.asarray(Image.open(painted_path).convert("RGB"))
        height_px, width_px = painted.shape[:2]
        min_pixels = max(64, int(0.01 * width_px * height_px / max(1, n)))
        simplify = float(self.config.get("simplify_frac", 0.01))
        masks = _partition_masks(painted, _PALETTE[:n])

        # Ruggedness -> mountain tag, measured on the real terrain art (not the flat paint).
        rugged: list[float] | None = None
        if source_path is not None:
            with Image.open(source_path) as opened:
                gray = np.asarray(opened.convert("L").resize((width_px, height_px)))
            rugged = [geometry.gradient_magnitude_mean(gray, mask) for mask in masks]
        ratio = float(self.config.get("mountain_ruggedness_ratio", 1.15))
        mean_rugged = (sum(rugged) / len(rugged)) if rugged else 0.0

        regions: list[ProposedRegion] = []
        for index, mask in enumerate(masks):
            if int(mask.sum()) < min_pixels:
                continue
            solid = geometry.largest_connected_component(mask)
            try:
                poly_px = geometry.mask_to_polygon(solid, epsilon_frac=simplify)
            except ValueError:
                continue
            polygon = tuple(
                (int(left + px / width_px * span_x), int(top + py / height_px * span_y))
                for px, py in poly_px
            )
            tag = "flat"
            if rugged is not None and mean_rugged > 0 and rugged[index] > ratio * mean_rugged:
                tag = "mountain"
            regions.append(ProposedRegion(polygon=polygon, tag=tag, name=f"Region {index + 1}"))
        return regions


def make_region_proposer(config: dict[str, Any] | None) -> RegionProposer:
    provider = str((config or {}).get("provider") or "grid").strip().lower()
    if provider in {"", "grid", "stub"}:
        return GridRegionProposer(config or {})
    if provider in {"openai", "image"}:
        return ImageDivisionProposer(config or {})
    raise ValueError(
        f"region proposer provider {provider!r} is not implemented. Use 'grid' (offline "
        f"default) or 'openai' (image division), or add a new provider here."
    )
