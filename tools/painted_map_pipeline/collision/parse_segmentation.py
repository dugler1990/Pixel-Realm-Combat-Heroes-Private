"""Parse flat color-coded Leonardo collision maps into game masks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass
class SegmentationColors:
    walkable: tuple[int, int, int] = (0, 255, 0)
    obstacle: tuple[int, int, int] = (255, 255, 255)
    canopy: tuple[int, int, int] = (0, 0, 255)
    void: tuple[int, int, int] = (0, 0, 0)
    tolerance: int = 48


def _color_distance(rgb: np.ndarray, target: tuple[int, int, int]) -> np.ndarray:
    t = np.array(target, dtype=np.float32)
    diff = rgb.astype(np.float32) - t
    return np.sqrt((diff * diff).sum(axis=2))


def parse_segmentation_image(
    image: Image.Image,
    *,
    colors: SegmentationColors | None = None,
    void_from_black: bool = True,
) -> dict[str, np.ndarray]:
    """Classify each pixel into walkable / obstacle / canopy / void masks."""
    colors = colors or SegmentationColors()
    rgb = np.array(image.convert("RGB"))
    tol = float(colors.tolerance)

    dist_walk = _color_distance(rgb, colors.walkable)
    dist_obs = _color_distance(rgb, colors.obstacle)
    dist_can = _color_distance(rgb, colors.canopy)
    dist_void = _color_distance(rgb, colors.void)

    stacked = np.stack([dist_void, dist_walk, dist_obs, dist_can], axis=0)
    labels = stacked.argmin(axis=0)
    # 0=void 1=walk 2=obs 3=can
    void = labels == 0
    walkable = labels == 1
    obstacle = labels == 2
    canopy = labels == 3

    if void_from_black:
        black = (rgb[:, :, 0] <= 30) & (rgb[:, :, 1] <= 30) & (rgb[:, :, 2] <= 30)
        void |= black
        walkable &= ~void
        canopy &= ~void

    # Pixels that matched nothing well -> treat as obstacle if bright, else walk
    min_dist = stacked.min(axis=0)
    ambiguous = min_dist > tol
    obstacle |= ambiguous & (rgb.mean(axis=2) > 160)
    walkable |= ambiguous & (rgb.mean(axis=2) <= 160)
    walkable &= ~obstacle & ~void
    canopy &= ~obstacle & ~void

    return {
        "void_mask": void,
        "walkable_mask": walkable,
        "obstacle_mask": obstacle | void,
        "canopy_mask": canopy & ~obstacle,
    }


def smooth_masks(masks: dict[str, np.ndarray], *, radius: int = 2) -> dict[str, np.ndarray]:
    """Light morphological smoothing on obstacle boundaries (small radius, not block grid)."""
    if radius <= 0:
        return masks
    obstacle = masks["obstacle_mask"].copy()
    h, w = obstacle.shape
    for _ in range(radius):
        padded = np.pad(obstacle, 1, mode="edge")
        dilated = np.zeros_like(obstacle)
        eroded = np.ones_like(obstacle)
        for dy in range(3):
            for dx in range(3):
                slice_ = padded[dy : dy + h, dx : dx + w]
                dilated |= slice_
                eroded &= slice_
        obstacle = dilated
    for _ in range(radius):
        padded = np.pad(obstacle, 1, mode="edge")
        eroded = np.ones_like(obstacle)
        for dy in range(3):
            for dx in range(3):
                eroded &= padded[dy : dy + h, dx : dx + w]
        obstacle = eroded
    void = masks["void_mask"]
    walkable = (~void) & (~obstacle)
    canopy = masks.get("canopy_mask", np.zeros_like(obstacle)) & walkable
    return {
        "void_mask": void,
        "walkable_mask": walkable,
        "obstacle_mask": obstacle | void,
        "canopy_mask": canopy,
    }


def resize_masks_nearest(masks: dict[str, np.ndarray], size: tuple[int, int]) -> dict[str, np.ndarray]:
    out = {}
    for key, mask in masks.items():
        img = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
        img = img.resize(size, Image.NEAREST)
        out[key] = np.array(img) > 127
    return out
