"""A draw's shape against the shape it was asked for: the marked overlay, its note, the scores.

Shared by every gate that checks a generated image against a mask: the level review loop
(``world_levels``), the building interiors and the character views
(``tools/boss_sprite_pipeline/view_gate.py``). One colour scheme and one wording, so a model sent
an overlay by any of them reads the same thing. numpy and PIL only.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

OVERLAY_MISSING = (255, 60, 255)
OVERLAY_SPILLED = (60, 255, 255)
OVERLAY_STRENGTH = 0.55


def mark_shape_error(image: Image.Image, should: np.ndarray, has: np.ndarray) -> Image.Image:
    """The image with its shape error painted on: magenta where it should have drawn and didn't,
    cyan where it drew outside the shape. `should` and `has` are boolean masks the size of `image`.
    To mark only what is missing, pass ``should | has`` as `should`."""
    rgb = image.convert("RGB")
    marked = np.asarray(rgb).copy()
    marked[should & ~has] = OVERLAY_MISSING
    marked[has & ~should] = OVERLAY_SPILLED
    return Image.blend(rgb, Image.fromarray(marked), OVERLAY_STRENGTH)


def shape_note(background: str) -> str:
    """What the overlay's two colours mean, for a draw on a `background` canvas. Sent verbatim with
    the overlay on a retry."""
    return (f"your previous attempt with its shape error marked: magenta is where you left it {background} "
            f"and it should be painted, cyan is where you painted and it should be {background}")


def shape_scores(should: np.ndarray, has: np.ndarray, bands=()) -> dict:
    """How far `has` is from `should`, in pixels.

    `iou`; `missing`: pixels of `should` not in `has`, over `should`; `spilled`: pixels of `has` not in
    `should`, over `has`. For each band `(name, row, columns)`, the left-to-right extent of each mask on
    that row within those columns (a slice), and `has` minus `should`.
    """
    union = int((should | has).sum())
    scores = {
        "iou": float((should & has).sum() / union) if union else 1.0,
        "missing": float((should & ~has).sum() / max(int(should.sum()), 1)),
        "spilled": float((has & ~should).sum() / max(int(has.sum()), 1)),
        "bands": {},
    }
    for name, row, columns in bands:
        widths = []
        for mask in (should, has):
            xs = np.nonzero(mask[row, columns])[0]
            widths.append(int(xs.max() - xs.min()) if len(xs) else 0)
        scores["bands"][name] = {"should": widths[0], "has": widths[1], "diff": widths[1] - widths[0]}
    return scores
