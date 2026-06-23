"""Build Leonardo input images that include mechanical collision hints."""

from __future__ import annotations

import numpy as np
from PIL import Image

from .derive import DeriveResult


def mechanical_flat_map(result: DeriveResult) -> Image.Image:
    """Flat RGB draft: black=void, green=walk, white=obstacle, blue=canopy."""
    h, w = result.obstacle_mask.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[result.void_mask] = (0, 0, 0)
    rgb[result.walkable_mask] = (0, 255, 0)
    rgb[result.obstacle_mask & ~result.void_mask] = (255, 255, 255)
    rgb[result.canopy_mask] = (0, 0, 255)
    return Image.fromarray(rgb, mode="RGB")


def painted_with_mechanical_overlay(painted: Image.Image, result: DeriveResult, *, alpha: float = 0.55) -> Image.Image:
    """Painted art with semi-transparent mechanical overlay for Leonardo hint mode."""
    base = painted.convert("RGBA")
    overlay = np.zeros((base.height, base.width, 4), dtype=np.uint8)
    a = int(max(0, min(255, round(alpha * 255))))
    overlay[result.walkable_mask] = (0, 255, 0, a)
    overlay[result.obstacle_mask & ~result.void_mask] = (255, 255, 255, min(255, a + 40))
    overlay[result.canopy_mask] = (0, 128, 255, a)
    overlay[result.void_mask] = (0, 0, 0, 200)
    over = Image.fromarray(overlay, mode="RGBA")
    return Image.alpha_composite(base, over)


def side_by_side_hint(painted: Image.Image, result: DeriveResult) -> Image.Image:
    """Left=painted art, right=mechanical flat map (same height)."""
    flat = mechanical_flat_map(result)
    pw, ph = painted.size
    fw, fh = flat.size
    if fh != ph:
        flat = flat.resize((int(round(fw * ph / fh)), ph), Image.NEAREST)
    combined = Image.new("RGB", (pw + flat.width, ph))
    combined.paste(painted.convert("RGB"), (0, 0))
    combined.paste(flat, (pw, 0))
    return combined
