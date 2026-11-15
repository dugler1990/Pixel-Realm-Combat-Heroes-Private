"""Where the paint landed, measured against the shape it was given.

Split out of ``land_fit`` so it can be used without it. ``land_fit`` is the warp, and the warp
needs scipy; measuring whether a return fits its mask needs numpy (and cv2, for which dark is
background) and nothing else. Keeping
the two in one module meant that anything wanting the measurement had to be able to import the
warp -- which is how the building interiors pass ended up with no shape check at all, on a
machine where scipy is not installed.

Nothing here changed in the move. ``land_fit`` re-exports both names, so every existing
``from .land_fit import CONTENT_LUMA_THRESHOLD`` keeps working.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

# Summed RGB above which a pixel counts as painted rather than background. Every measurement
# of "where the art is" uses this one number, so a picture of an error and the score for it
# cannot disagree about which pixels are involved.
CONTENT_LUMA_THRESHOLD = 40


def background(
    rgb_sum: np.ndarray, outside: np.ndarray | None = None, *, threshold: int = CONTENT_LUMA_THRESHOLD
) -> np.ndarray:
    """The unpainted black: dark pixels joined to the canvas edge or to ``outside``.

    A level sits on black, so "dark" alone cannot tell background from art: crevices and
    shadows inside the land are dark too, and counting them as unpainted marked correct art as
    missing (level 21: 22,850 "missing" px, 0 real). Dark only counts as background when it
    connects (4-neighbour) to the canvas border or to a dark pixel in ``outside`` (the area
    outside the shape, so a shape that fills the canvas still has somewhere to start from).
    Dark enclosed by paint is art.
    """
    dark = rgb_sum <= threshold
    if not dark.any():
        return dark
    count, labels = cv2.connectedComponents(dark.astype(np.uint8), connectivity=4)
    seeds = np.zeros(dark.shape, dtype=bool)
    seeds[0, :] = seeds[-1, :] = seeds[:, 0] = seeds[:, -1] = True
    if outside is not None:
        seeds |= outside
    touching = np.unique(labels[seeds & dark])
    return np.isin(labels, touching[touching > 0])


def painted(
    image: Image.Image | np.ndarray,
    outside: np.ndarray | None = None,
    *,
    threshold: int = CONTENT_LUMA_THRESHOLD,
) -> np.ndarray:
    """Every pixel that is not background (see ``background``)."""
    pixels = np.asarray(image.convert("RGB")) if isinstance(image, Image.Image) else image
    return ~background(pixels[..., :3].astype(np.int32).sum(axis=2), outside, threshold=threshold)


def footprint_iou(
    generated: Image.Image,
    generation_mask: Image.Image,
    *,
    content_luma_threshold: int = CONTENT_LUMA_THRESHOLD,
    enclosed_is_art: bool = False,
) -> float:
    """IoU between the generated land footprint and the template silhouette.

    Measured on the raw generation, before any warp. This is the number that
    distinguishes a faithful repaint from a reframed one: a model that re-crops the
    reference to its content bbox scores ~0.2 here while still warping cleanly.

    ``enclosed_is_art``: dark pixels enclosed by paint count as painted (``painted``). The
    world levels pass True; off by default so other callers (interiors) keep their numbers.
    """
    pixels = np.asarray(generated.convert("RGB"))
    mask = np.asarray(generation_mask.convert("L")) > 0
    if pixels.shape[:2] != mask.shape:
        raise ValueError(
            f"generated size {pixels.shape[1]}x{pixels.shape[0]} does not match "
            f"generation mask {mask.shape[1]}x{mask.shape[0]}"
        )
    if enclosed_is_art:
        content = painted(pixels, ~mask, threshold=content_luma_threshold)
    else:
        content = pixels.astype(np.int32).sum(axis=2) > content_luma_threshold
    union = np.count_nonzero(content | mask)
    if union == 0:
        return 0.0
    return float(np.count_nonzero(content & mask) / union)
