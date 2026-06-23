"""Heuristic walk / obstacle mask derivation from a painted chunk PNG."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from PIL import Image


@dataclass
class DeriveConfig:
    void_rgb_max: int = 25
    walkable_luminance_min: float = 92.0
    obstacle_luminance_max: float = 72.0
    edge_gradient_min: float = 28.0
    snow_saturation_max: float = 58.0
    rock_saturation_min: float = 32.0
    collision_cell_px: int = 64
    morphology_radius: int = 1
    min_obstacle_cell_ratio: float = 0.4
    canopy_luminance_min: float = 45.0
    canopy_luminance_max: float = 88.0
    canopy_saturation_min: float = 18.0
    restrict_to_content_bbox: bool = True
    content_bbox_margin_px: int = 8

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "DeriveConfig":
        if not data:
            return cls()
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class DeriveResult:
    obstacle_mask: np.ndarray
    walkable_mask: np.ndarray
    void_mask: np.ndarray
    canopy_mask: np.ndarray
    cell_size: int
    stats: dict[str, float] = field(default_factory=dict)


def _luminance(rgb: np.ndarray) -> np.ndarray:
    return (
        0.299 * rgb[:, :, 0].astype(np.float32)
        + 0.587 * rgb[:, :, 1].astype(np.float32)
        + 0.114 * rgb[:, :, 2].astype(np.float32)
    )


def _saturation(rgb: np.ndarray) -> np.ndarray:
    rgbf = rgb.astype(np.float32)
    cmax = rgbf.max(axis=2)
    cmin = rgbf.min(axis=2)
    delta = cmax - cmin
    with np.errstate(divide="ignore", invalid="ignore"):
        sat = np.where(cmax > 0, delta / cmax, 0.0)
    return sat * 255.0


def _gradient_magnitude(lum: np.ndarray) -> np.ndarray:
    gy, gx = np.gradient(lum)
    return np.hypot(gx, gy)


def _pool_down(mask: np.ndarray, cell: int, reducer) -> np.ndarray:
    h, w = mask.shape
    h_trim = (h // cell) * cell
    w_trim = (w // cell) * cell
    trimmed = mask[:h_trim, :w_trim]
    blocks = trimmed.reshape(h_trim // cell, cell, w_trim // cell, cell)
    return reducer(blocks, axis=(1, 3))


def _pool_up(mask: np.ndarray, cell: int, target_shape: tuple[int, int]) -> np.ndarray:
    upscaled = np.repeat(np.repeat(mask, cell, axis=0), cell, axis=1)
    th, tw = target_shape
    out = np.zeros((th, tw), dtype=bool)
    h = min(upscaled.shape[0], th)
    w = min(upscaled.shape[1], tw)
    out[:h, :w] = upscaled[:h, :w]
    return out


def _morphology(mask: np.ndarray, radius: int, op: str) -> np.ndarray:
    if radius <= 0:
        return mask
    out = mask.copy()
    h, w = mask.shape
    for _ in range(radius):
        padded = np.pad(out, 1, mode="edge")
        neighbors = []
        for dy in range(3):
            for dx in range(3):
                neighbors.append(padded[dy : dy + h, dx : dx + w])
        stacked = np.stack(neighbors, axis=0)
        if op == "dilate":
            out = stacked.any(axis=0)
        elif op == "erode":
            out = stacked.all(axis=0)
        else:
            raise ValueError(f"unknown morphology op {op!r}")
    return out


def _content_bbox(void: np.ndarray, margin: int) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(~void)
    if len(xs) == 0:
        return None
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    h, w = void.shape
    m = max(0, int(margin))
    return max(0, x0 - m), max(0, y0 - m), min(w - 1, x1 + m), min(h - 1, y1 + m)


def derive_collision_masks(image: Image.Image, config: DeriveConfig | None = None) -> DeriveResult:
    """Return full-resolution boolean masks aligned to the painted chunk."""
    cfg = config or DeriveConfig()
    rgb = np.array(image.convert("RGB"))
    h, w = rgb.shape[:2]
    cell = max(4, int(cfg.collision_cell_px))

    void = (
        (rgb[:, :, 0] <= cfg.void_rgb_max)
        & (rgb[:, :, 1] <= cfg.void_rgb_max)
        & (rgb[:, :, 2] <= cfg.void_rgb_max)
    )
    lum = _luminance(rgb)
    sat = _saturation(rgb)
    grad = _gradient_magnitude(lum)

    content = ~void
    in_region = content
    if cfg.restrict_to_content_bbox:
        bbox = _content_bbox(void, cfg.content_bbox_margin_px)
        if bbox is not None:
            x0, y0, x1, y1 = bbox
            in_region = np.zeros_like(content)
            in_region[y0 : y1 + 1, x0 : x1 + 1] = True
            in_region &= content

    snow_like = in_region & (lum >= cfg.walkable_luminance_min) & (sat <= cfg.snow_saturation_max)
    rock_like = in_region & (
        (lum <= cfg.obstacle_luminance_max)
        | ((sat >= cfg.rock_saturation_min) & (lum < cfg.walkable_luminance_min))
    )
    edge_obstacle = (
        in_region
        & (grad >= cfg.edge_gradient_min)
        & (lum <= cfg.walkable_luminance_min)
        & ~snow_like
    )
    raw_obstacle = void | rock_like | edge_obstacle

    canopy = (
        in_region
        & ~raw_obstacle
        & (lum >= cfg.canopy_luminance_min)
        & (lum <= cfg.canopy_luminance_max)
        & (sat >= cfg.canopy_saturation_min)
    )

    obstacle_cells = _pool_down(raw_obstacle, cell, np.mean) >= cfg.min_obstacle_cell_ratio
    obstacle_cells = _morphology(obstacle_cells, cfg.morphology_radius, "dilate")
    obstacle_cells = _morphology(obstacle_cells, cfg.morphology_radius, "erode")
    obstacle = _pool_up(obstacle_cells, cell, (h, w)) | void

    walkable = (~void) & (~obstacle)
    canopy = canopy & walkable

    content = ~void
    stats = {
        "void_ratio": float(void.mean()),
        "obstacle_ratio": float(obstacle[content].mean()) if content.any() else 0.0,
        "walkable_ratio": float(walkable[content].mean()) if content.any() else 0.0,
        "canopy_ratio": float(canopy[content].mean()) if content.any() else 0.0,
    }
    return DeriveResult(
        obstacle_mask=obstacle,
        walkable_mask=walkable,
        void_mask=void,
        canopy_mask=canopy,
        cell_size=cell,
        stats=stats,
    )


def obstacle_mask_to_rgba(obstacle_mask: np.ndarray) -> Image.Image:
    """Engine collision sprite: opaque white = solid, transparent = walkable."""
    h, w = obstacle_mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[obstacle_mask, :3] = 255
    rgba[obstacle_mask, 3] = 255
    return Image.fromarray(rgba, mode="RGBA")


def walkable_preview(painted: Image.Image, result: DeriveResult) -> Image.Image:
    base = painted.convert("RGBA")
    overlay = np.zeros((base.height, base.width, 4), dtype=np.uint8)
    overlay[result.walkable_mask] = (40, 200, 80, 90)
    overlay[result.obstacle_mask & ~result.void_mask] = (220, 60, 60, 120)
    overlay[result.canopy_mask] = (80, 140, 255, 110)
    over = Image.fromarray(overlay, mode="RGBA")
    return Image.alpha_composite(base, over)
