"""Deterministic colour alignment against accepted padding.

The shift is learned from the model's raw picture and the accepted padding at the same spots,
one shift per colour group. That shift is added to the new cell only. Each new-cell pixel is
then replaced with the nearest of 256 colours that actually occur in the accepted padding.
The accepted padding is not written here. The caller pastes it afterwards. Black gaps stay black.
"""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

CONTENT_MIN_RGB_SUM = 20
LAB_BIN_SIZE = 8
MIN_BIN_SAMPLES = 20
MAX_PAIR_SAMPLES = 250_000
LUT_NEIGHBOURS = 8
PALETTE_COLOURS = 256
PALETTE_SAMPLE = 120_000


def _paired_delta_lut(
    source_rgb: np.ndarray,
    accepted_rgb: np.ndarray,
    locked: np.ndarray,
) -> tuple[np.ndarray, int]:
    """One Lab shift per colour group, from raw model pixels and accepted padding at the same spots."""
    source = source_rgb[locked]
    target = accepted_rgb[locked]
    valid = (
        (source.sum(axis=1) > CONTENT_MIN_RGB_SUM)
        & (target.sum(axis=1) > CONTENT_MIN_RGB_SUM)
    )
    source, target = source[valid], target[valid]
    if len(source) < 1_000:
        raise ValueError(
            f"paired colour alignment needs at least 1000 painted padding pixels, got {len(source)}"
        )
    if len(source) > MAX_PAIR_SAMPLES:
        indices = np.linspace(0, len(source) - 1, MAX_PAIR_SAMPLES, dtype=np.int64)
        source, target = source[indices], target[indices]

    source_lab = cv2.cvtColor(
        source.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB
    ).reshape(-1, 3).astype(np.float32)
    target_lab = cv2.cvtColor(
        target.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB
    ).reshape(-1, 3).astype(np.float32)
    keys, inverse = np.unique(
        source_lab.astype(np.int32) // LAB_BIN_SIZE,
        axis=0,
        return_inverse=True,
    )

    representatives, deltas = [], []
    for index in range(len(keys)):
        members = inverse == index
        if int(members.sum()) < MIN_BIN_SAMPLES:
            continue
        representatives.append(np.median(source_lab[members], axis=0))
        deltas.append(np.median(target_lab[members] - source_lab[members], axis=0))
    representatives = np.asarray(representatives, dtype=np.float32)
    deltas = np.asarray(deltas, dtype=np.float32)
    if not len(representatives):
        raise ValueError("paired colour alignment found no populated colour bins")

    levels = np.arange(256 // LAB_BIN_SIZE, dtype=np.float32) * LAB_BIN_SIZE
    levels += LAB_BIN_SIZE / 2
    lightness, green_red, blue_yellow = np.meshgrid(levels, levels, levels, indexing="ij")
    grid = np.stack((lightness, green_red, blue_yellow), axis=-1).reshape(-1, 3)
    lookup = np.empty_like(grid)
    neighbour_count = min(LUT_NEIGHBOURS, len(representatives))
    for start in range(0, len(grid), 1024):
        cells = grid[start : start + 1024]
        distance = ((cells[:, None, :] - representatives[None, :, :]) ** 2).sum(axis=2)
        nearest = np.argpartition(distance, neighbour_count - 1, axis=1)[:, :neighbour_count]
        nearest_distance = np.take_along_axis(distance, nearest, axis=1)
        weight = 1.0 / (nearest_distance + 16.0)
        lookup[start : start + len(cells)] = (
            deltas[nearest] * weight[..., None]
        ).sum(axis=1) / weight.sum(axis=1)[:, None]
    return lookup, len(representatives)


def _padding_palette(accepted_rgb: np.ndarray, locked: np.ndarray) -> np.ndarray:
    """Up to 256 colours that actually occur in the accepted padding."""
    pixels = accepted_rgb[locked]
    pixels = pixels[pixels.sum(axis=1) > CONTENT_MIN_RGB_SUM]
    if len(pixels) > PALETTE_SAMPLE:
        pixels = pixels[np.linspace(0, len(pixels) - 1, PALETTE_SAMPLE, dtype=np.int64)]
    unique = np.unique(pixels, axis=0)
    if len(unique) <= PALETTE_COLOURS:
        return unique
    lab = cv2.cvtColor(
        pixels.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB
    ).reshape(-1, 3).astype(np.float32)
    cv2.setRNGSeed(0)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.1)
    _, _, centers = cv2.kmeans(
        lab, PALETTE_COLOURS, None, criteria, 3, cv2.KMEANS_PP_CENTERS
    )
    chosen = [pixels[int(((lab - center) ** 2).sum(axis=1).argmin())] for center in centers]
    return np.unique(np.asarray(chosen, dtype=np.uint8), axis=0)


def _snap_to_palette(rgb: np.ndarray, mask: np.ndarray, palette: np.ndarray) -> None:
    """Replace masked pixels with the nearest real padding colour."""
    if not mask.any() or not len(palette):
        return
    palette_lab = cv2.cvtColor(
        palette.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB
    ).reshape(-1, 3).astype(np.float32)
    levels = np.arange(32, dtype=np.float32) * 8 + 4
    lightness, green_red, blue_yellow = np.meshgrid(levels, levels, levels, indexing="ij")
    grid = np.stack((lightness, green_red, blue_yellow), axis=-1).reshape(-1, 3)
    nearest = np.empty(len(grid), dtype=np.int32)
    for start in range(0, len(grid), 1024):
        block = grid[start : start + 1024]
        distance = ((block[:, None, :] - palette_lab[None, :, :]) ** 2).sum(axis=2)
        nearest[start : start + len(block)] = distance.argmin(axis=1)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.int32) // 8
    bins = lab[..., 0] * 1024 + lab[..., 1] * 32 + lab[..., 2]
    rgb[mask] = palette[nearest[bins]][mask]


def align_to_paired_padding(
    image: Image.Image,
    accepted_padding: Image.Image,
    locked_mask: Image.Image,
    pending_mask: Image.Image,
    *,
    raw: Image.Image | None = None,
    strength: float = 1.0,
) -> tuple[Image.Image, dict]:
    """Shift the new cell from same-spot pairs, then snap it to real accepted-padding colours.

    ``accepted_padding`` is the neighbours' pixels. ``raw`` is the model output before cut or
    warp. The pairs are read from ``raw`` when it is passed, because a cut deletes the model's
    overlap. The shift and the snap write the new cell only. Accepted padding and black gaps
    are not written.
    """
    if strength < 0:
        raise ValueError("paired colour alignment strength must be non-negative")
    rgba = np.asarray(image.convert("RGBA")).copy()
    accepted = np.asarray(accepted_padding.convert("RGB"))
    locked = np.asarray(locked_mask.convert("L")) > 0
    pending = np.asarray(pending_mask.convert("L")) > 0
    if not locked.any():
        raise ValueError("paired colour alignment requires accepted padding")
    if rgba.shape[:2] != accepted.shape[:2] or locked.shape != pending.shape:
        raise ValueError("paired colour alignment inputs must share one canvas size")
    pair_source = image if raw is None else raw
    if pair_source.size != image.size:
        raise ValueError("raw generation must share the placed image's canvas size")

    pair_rgb = np.asarray(pair_source.convert("RGB"))
    rgb = rgba[..., :3]
    painted_pending = pending & (rgb.sum(axis=2) > CONTENT_MIN_RGB_SUM)
    lookup, populated_bins = _paired_delta_lut(pair_rgb, accepted, locked)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    quantized = lab.astype(np.int32) // LAB_BIN_SIZE
    indices = quantized[..., 0] * 1024 + quantized[..., 1] * 32 + quantized[..., 2]
    corrected_lab = np.clip(
        lab.astype(np.float32) + lookup[indices] * float(strength),
        0,
        255,
    ).astype(np.uint8)
    corrected_rgb = cv2.cvtColor(corrected_lab, cv2.COLOR_LAB2RGB)
    rgb[painted_pending] = corrected_rgb[painted_pending]
    palette = _padding_palette(accepted, locked)
    _snap_to_palette(rgb, painted_pending, palette)
    return Image.fromarray(rgba), {
        "strength": float(strength),
        "paired_pixels": int(locked.sum()),
        "corrected_pixels": int(painted_pending.sum()),
        "populated_colour_bins": int(populated_bins),
        "palette_colours": int(len(palette)),
    }
