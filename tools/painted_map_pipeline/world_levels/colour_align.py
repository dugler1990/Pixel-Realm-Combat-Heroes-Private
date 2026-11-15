"""Deterministic colour alignment against accepted padding.

Steps, written to every pixel the model drew. Background black (joined to the canvas edge)
stays black; dark art enclosed by paint is recoloured like the rest. The caller pastes the
padding over the result afterwards, so a feathered paste always fades between two corrected
sides:

1. Swap: one shift per colour group, learned from the model's raw picture and the accepted
   padding at the same spots.
2. Brightness mix ("match" only): the new cell's lightness is remapped so dark, mid and light
   occur in the same proportions as in the padding. The swap alone pulls toward grey, because
   the model drew details in slightly different places and each group's median mixes them.
3. Join fix ("match" only): the place-by-place difference between the padding and the model's
   swapped copy of it, smoothed over ``JOIN_SIGMA`` px, carried into the new cell and faded out
   over ``JOIN_FADE`` px. Corrects chunk by chunk where the eye compares the two sides.
4. Snap: each pixel becomes the nearest of 256 colours that occur in the accepted padding.

Level 06 attempt 1, learned on half the padding and scored on the other half (16 px chunk
error / brightness spread vs padding): swap 14.4 / 0.92, match 12.2 / 1.05.
"""

from __future__ import annotations

import hashlib

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
JOIN_SIGMA = 24
JOIN_FADE = 200
JOIN_SCALE = 4  # the join fix is smoothed over 24 px, so it is worked out at 1/4 size
LIGHTNESS_BINS = 4096  # brightness mix ranks lightness in 1/16-unit steps (L is 0-255 here)
COLOUR_METHODS = ("match", "swap")


def _painted(rgb: np.ndarray, within: np.ndarray | None = None) -> np.ndarray:
    """Pixels that are art, not background black (``footprint.background``, at this module's
    threshold). Dark art enclosed by paint counts as art. ``within``: only that area is looked
    at (the rest is treated as bright), so black elsewhere on the canvas cannot reach into it."""
    from .footprint import background

    summed = rgb[..., :3].astype(np.int32).sum(axis=2)
    if within is not None:
        summed = np.where(within, summed, 255 * 3)
    return ~background(summed, threshold=CONTENT_MIN_RGB_SUM)


def _paired_delta_lut(
    source_rgb: np.ndarray,
    accepted_rgb: np.ndarray,
    pairs: np.ndarray,
) -> tuple[np.ndarray, int]:
    """One Lab shift per colour group, from raw model pixels and accepted padding at the same
    spots. ``pairs``: where both are art (not background black)."""
    source = source_rgb[pairs]
    target = accepted_rgb[pairs]
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


_PALETTE_CACHE: dict[str, np.ndarray] = {}


def _padding_palette(accepted_rgb: np.ndarray, locked: np.ndarray) -> np.ndarray:
    """Up to 256 colours that actually occur in the accepted padding.

    The k-means is seeded, so the same padding always gives the same palette: it is kept per
    padding (hash of its pixels and mask) for the life of the process. Every attempt of a level
    shares one padding, so in the review page only the first align of a level pays for it.
    """
    key = hashlib.sha1(
        np.ascontiguousarray(accepted_rgb[locked]).tobytes()
        + np.packbits(locked).tobytes()
        + repr((locked.shape, PALETTE_COLOURS, PALETTE_SAMPLE, CONTENT_MIN_RGB_SUM)).encode()
    ).hexdigest()
    if key not in _PALETTE_CACHE:
        _PALETTE_CACHE[key] = _build_padding_palette(accepted_rgb, locked)
    return _PALETTE_CACHE[key].copy()


def _build_padding_palette(accepted_rgb: np.ndarray, locked: np.ndarray) -> np.ndarray:
    """``locked``: the padding pixels to take colours from (the caller leaves background out)."""
    pixels = accepted_rgb[locked]
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


def _lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)


def _apply_lookup(rgb: np.ndarray, lookup: np.ndarray, strength: float) -> np.ndarray:
    """The swap: each pixel shifted by its colour group's learned Lab shift (float Lab out)."""
    lab = _lab(rgb)
    quantized = lab.astype(np.int32) // LAB_BIN_SIZE
    indices = quantized[..., 0] * 1024 + quantized[..., 1] * 32 + quantized[..., 2]
    return lab + lookup[indices] * float(strength)


def _match_lightness(
    lab: np.ndarray, region: np.ndarray, target: np.ndarray, apply_to: np.ndarray
) -> np.ndarray:
    """Remap lightness so that inside ``region`` its distribution equals ``target``.

    The mapping is learned from ``region`` (rank for rank) and applied to every pixel of
    ``apply_to``, so pixels outside the region with the same lightness get the same answer.
    Only L moves; the hue the swap chose is kept. Ranks are counted per lightness step of
    1/16 (``LIGHTNESS_BINS``) instead of per pixel: same answer to well under one L unit,
    without sorting millions of pixels.
    """
    if not region.any() or not len(target):
        return lab

    def step(values: np.ndarray) -> np.ndarray:
        return np.clip((values * (LIGHTNESS_BINS / 256.0)).astype(np.int32), 0, LIGHTNESS_BINS - 1)

    counts = np.bincount(step(lab[..., 0][region]), minlength=LIGHTNESS_BINS)
    below = np.cumsum(counts) - counts
    # Middle rank of equal values: with few distinct colours, the lowest rank would send a
    # whole colour to the bottom of its share of the target.
    last = below + counts - 1
    rank = (below + np.maximum(last, below)) / 2.0 / max(int(counts.sum()) - 1, 1)
    remap = np.interp(
        np.clip(rank, 0.0, 1.0), np.linspace(0.0, 1.0, len(target)), np.sort(target)
    )
    out = lab.copy()
    out[..., 0][apply_to] = remap[step(lab[..., 0][apply_to])]
    return out


def _join_correction(difference: np.ndarray, known: np.ndarray, locked: np.ndarray) -> np.ndarray:
    """``difference`` (Lab) where ``known``, smoothed, carried to every pixel, faded from the padding.

    Smoothed by normalised convolution so the gaps in ``known`` do not pull it toward zero.
    Beyond the smoothing's reach each pixel takes the nearest smoothed value, then the whole
    correction fades with distance from the padding. The smoothing and the fill are worked out
    at 1/``JOIN_SCALE`` size and scaled back up: the result is a 24 px blur, so the small grid
    loses nothing visible. The fade is full size.
    """
    height, width = known.shape
    small = (max(1, -(-width // JOIN_SCALE)), max(1, -(-height // JOIN_SCALE)))
    weight_mask = known.astype(np.float32)
    weighted = (difference * weight_mask[..., None]).astype(np.float32)
    blur = lambda x: cv2.GaussianBlur(x, (0, 0), JOIN_SIGMA / JOIN_SCALE)  # noqa: E731
    weight = blur(cv2.resize(weight_mask, small, interpolation=cv2.INTER_AREA))
    reached = weight > 0.02
    if not reached.any():
        return np.zeros_like(difference)
    local = blur(cv2.resize(weighted, small, interpolation=cv2.INTER_AREA)) / np.maximum(
        weight, 1e-6
    )[..., None]
    _, labels = cv2.distanceTransformWithLabels(
        (~reached).astype(np.uint8), cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL
    )
    ys, xs = np.where(reached)
    by_label = np.zeros(int(labels.max()) + 1, dtype=np.int64)
    by_label[labels[reached]] = np.arange(len(ys))
    filled = cv2.resize(
        np.ascontiguousarray(local[ys[by_label[labels]], xs[by_label[labels]]], dtype=np.float32),
        (width, height),
        interpolation=cv2.INTER_LINEAR,
    )
    to_padding = cv2.distanceTransform((~locked).astype(np.uint8), cv2.DIST_L2, 5)
    return filled * np.exp(-to_padding / JOIN_FADE)[..., None]


def align_to_paired_padding(
    image: Image.Image,
    accepted_padding: Image.Image,
    locked_mask: Image.Image,
    pending_mask: Image.Image,
    *,
    raw: Image.Image | None = None,
    strength: float = 1.0,
    method: str = "match",
) -> tuple[Image.Image, dict]:
    """Recolour the new cell from same-spot pairs, then snap it to real accepted-padding colours.

    ``accepted_padding`` is the neighbours' pixels. ``raw`` is the model output before cut or
    warp. The pairs are read from ``raw`` when it is passed, because a cut deletes the model's
    overlap. ``method`` is "match" (swap, brightness mix, join fix, snap) or "swap" (swap and
    snap only, the earlier behaviour). Every drawn pixel of ``image`` is written, background
    black is not; the caller pastes the padding over the result.
    """
    if strength < 0:
        raise ValueError("paired colour alignment strength must be non-negative")
    if method not in COLOUR_METHODS:
        raise ValueError(f"colour method must be one of {COLOUR_METHODS}, got {method!r}")
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
    # Every pixel the model drew is recoloured; only background black is left (black joined
    # to the canvas edge; dark art enclosed by paint is recoloured like the rest). The masks
    # below choose what the colours are learned from, never where they are written, so a later
    # step (padding paste, feather, padding strips left out) always sees a recoloured image.
    write = _painted(rgb)
    painted_pending = pending & write
    painted_under = locked & write
    accepted_art = locked & _painted(accepted, locked)
    painted_locked = accepted_art & _painted(pair_rgb)
    lookup, populated_bins = _paired_delta_lut(pair_rgb, accepted, painted_locked)
    corrected = _apply_lookup(rgb, lookup, strength)
    if method == "match":
        accepted_lab = _lab(accepted)
        corrected = _match_lightness(
            corrected, painted_pending, accepted_lab[..., 0][painted_locked], write
        )
        model_copy = _apply_lookup(pair_rgb, lookup, strength)
        corrected = corrected + _join_correction(accepted_lab - model_copy, painted_locked, locked) * float(strength)
    corrected_rgb = cv2.cvtColor(np.clip(corrected, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
    rgb[write] = corrected_rgb[write]
    palette = _padding_palette(accepted, accepted_art)
    _snap_to_palette(rgb, write, palette)
    return Image.fromarray(rgba), {
        "method": method,
        "strength": float(strength),
        "paired_pixels": int(locked.sum()),
        "corrected_pixels": int(painted_pending.sum()),
        "corrected_under_padding": int(painted_under.sum()),
        "corrected_total": int(write.sum()),
        "populated_colour_bins": int(populated_bins),
        "palette_colours": int(len(palette)),
    }
