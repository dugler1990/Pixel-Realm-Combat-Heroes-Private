"""Where the paint landed, measured against the shape it was given.

Split out of ``land_fit`` so it can be used without it. ``land_fit`` is the warp, and the warp
needs scipy; measuring whether a return fits its mask needs numpy and nothing else. Keeping
the two in one module meant that anything wanting the measurement had to be able to import the
warp -- which is how the building interiors pass ended up with no shape check at all, on a
machine where scipy is not installed.

Nothing here changed in the move. ``land_fit`` re-exports both names, so every existing
``from .land_fit import CONTENT_LUMA_THRESHOLD`` keeps working.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# Summed RGB above which a pixel counts as painted rather than background. Every measurement
# of "where the art is" uses this one number, so a picture of an error and the score for it
# cannot disagree about which pixels are involved.
CONTENT_LUMA_THRESHOLD = 40


def footprint_iou(
    generated: Image.Image,
    generation_mask: Image.Image,
    *,
    content_luma_threshold: int = CONTENT_LUMA_THRESHOLD,
) -> float:
    """IoU between the generated land footprint and the template silhouette.

    Measured on the raw generation, before any warp. This is the number that
    distinguishes a faithful repaint from a reframed one: a model that re-crops the
    reference to its content bbox scores ~0.2 here while still warping cleanly.
    """
    pixels = np.asarray(generated.convert("RGBA"))
    content = pixels[:, :, :3].sum(axis=2) > content_luma_threshold
    mask = np.asarray(generation_mask.convert("L")) > 0
    if content.shape != mask.shape:
        raise ValueError(
            f"generated size {content.shape[1]}x{content.shape[0]} does not match "
            f"generation mask {mask.shape[1]}x{mask.shape[0]}"
        )
    union = np.count_nonzero(content | mask)
    if union == 0:
        return 0.0
    return float(np.count_nonzero(content & mask) / union)
