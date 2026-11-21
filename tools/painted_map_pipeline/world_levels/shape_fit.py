"""How well the model's painted area fills the level's shape at a padding offset.

The offset is the review page's (dx, dy): how far the padding moved right/down to sit on the
generation. Placing with it (warp off) moves the generation by (-dx, -dy), edge pixels
repeated (``renderers.frame.shift_image``), then cut and paste the padding. So the holes a cut
result will have at an offset are the new-cell pixels the moved painted area does not reach;
the padding covers the rest. "Painted" is ``footprint.painted``: dark art enclosed by paint
counts, only black joined to the black outside does not.

``best`` is the offset that leaves the fewest holes (ties: the one nearest 0, 0): a 1/4-size
search over +-``limit`` px, then every offset within 4 px of the winner at full size. It looks
at shape only; the padding's colour match is judged by eye on the page.
"""

from __future__ import annotations

import numpy as np

from .footprint import painted

SEARCH_LIMIT = 40
COARSE = 4


def shift_mask(mask: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """``mask`` moved right ``dx`` and down ``dy``, edges repeated (as ``shift_image``)."""
    if not dx and not dy:
        return mask
    pad_x, pad_y = abs(dx), abs(dy)
    padded = np.pad(mask, ((pad_y, pad_y), (pad_x, pad_x)), mode="edge")
    top, left = pad_y - dy, pad_x - dx
    return padded[top : top + mask.shape[0], left : left + mask.shape[1]]


class ShapeFit:
    """The painted area of one raw generation against one level's shape."""

    def __init__(self, raw_rgb: np.ndarray, shape: np.ndarray, new_cell: np.ndarray) -> None:
        if raw_rgb.shape[:2] != shape.shape or shape.shape != new_cell.shape:
            raise ValueError("the raw generation and the masks must share one canvas size")
        self.shape = shape
        self.new_cell = new_cell & shape
        self.drawn = painted(raw_rgb, ~shape)
        self.total = int(self.new_cell.sum())

    def holes(self, offset: tuple[int, int]) -> np.ndarray:
        """New-cell pixels the generation leaves unpainted when placed at ``offset``."""
        dx, dy = offset
        return self.new_cell & ~shift_mask(self.drawn, -dx, -dy)

    def score(self, offset: tuple[int, int]) -> dict:
        missing = int(self.holes(offset).sum())
        return {
            "offset": [int(offset[0]), int(offset[1])],
            "missing_px": missing,
            "cut_iou": round(1.0 - missing / self.total, 6) if self.total else 1.0,
        }

    def best(self, limit: int = SEARCH_LIMIT) -> dict:
        def pick(candidates, count):
            return min(candidates, key=lambda o: (count(o), abs(o[0]) + abs(o[1])))

        small = lambda m: m[::COARSE, ::COARSE]  # noqa: E731
        drawn, cell = small(self.drawn), small(self.new_cell)
        reach = limit // COARSE
        coarse = pick(
            [(dx, dy) for dy in range(-reach, reach + 1) for dx in range(-reach, reach + 1)],
            lambda o: int((cell & ~shift_mask(drawn, -o[0], -o[1])).sum()),
        )
        centre = (coarse[0] * COARSE, coarse[1] * COARSE)
        fine = pick(
            [(centre[0] + dx, centre[1] + dy)
             for dy in range(-COARSE, COARSE + 1) for dx in range(-COARSE, COARSE + 1)
             if abs(centre[0] + dx) <= limit and abs(centre[1] + dy) <= limit],
            lambda o: int(self.holes(o).sum()),
        )
        return self.score(fine)
