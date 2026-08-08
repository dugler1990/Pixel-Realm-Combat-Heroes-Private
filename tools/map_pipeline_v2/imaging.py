"""Small shared imaging helpers (numpy/PIL). Pure, no config, no state."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

CONTENT_LUMA_THRESHOLD = 40  # sum of RGB above this counts as painted "land"


def load_rgba(path: str | Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("RGBA"))


def load_mask_bool(path: str | Path) -> np.ndarray:
    with Image.open(path) as img:
        return np.asarray(img.convert("L")) > 0


def content_bool(rgba: np.ndarray, threshold: int = CONTENT_LUMA_THRESHOLD) -> np.ndarray:
    """Non-black pixels = painted land."""
    return rgba[:, :, :3].astype(np.int32).sum(axis=2) > threshold


def iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = int(np.count_nonzero(a & b))
    union = int(np.count_nonzero(a | b))
    return inter / union if union else 0.0


def area_ratio(content: np.ndarray, silhouette: np.ndarray) -> float:
    denom = int(np.count_nonzero(silhouette))
    return (int(np.count_nonzero(content)) / denom) if denom else 0.0


def save_rgba(arr: np.ndarray, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(arr.astype(np.uint8), mode="RGBA").save(path)


def mask_to_silhouette(
    raw: np.ndarray,
    silhouette: np.ndarray,
    outside_color: tuple[int, int, int, int],
) -> np.ndarray:
    """Composite raw content inside the silhouette, pure `outside_color` elsewhere.
    This is a hard crop — no warping, no resampling of the outline."""
    out = np.empty_like(raw)
    out[:, :] = np.asarray(outside_color, dtype=np.uint8)
    out[silhouette] = raw[silhouette]
    return out
