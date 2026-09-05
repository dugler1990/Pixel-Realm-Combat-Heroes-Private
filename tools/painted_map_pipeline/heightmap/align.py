"""Resize a model heightmap to source.png and score registration.

Void punch is for preview / hand-edit only. Runtime rebuilds the land mask from
source.png. Duplicate VOID_* here; tests/test_terrain_height.py asserts they match
Code/terrain_height.py. Do not import Code from this package (Settings chdirs).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from ..image_client import _resample_filter

VOID_RGB_MAX = 12
VOID_ALPHA_MAX = 8

QC_MAX_SHIFT_PX = 8
QC_MIN_RESPONSE = 0.015

Image.MAX_IMAGE_PIXELS = None


class HeightmapQCError(RuntimeError):
    pass


def void_mask_rgba(source_rgba: np.ndarray) -> np.ndarray:
    rgb_max = source_rgba[:, :, :3].max(axis=2)
    alpha = source_rgba[:, :, 3]
    return (alpha < VOID_ALPHA_MAX) | (rgb_max < VOID_RGB_MAX)


def punch_void(height_l: Image.Image, source_rgba: Image.Image) -> Image.Image:
    src = np.asarray(source_rgba.convert("RGBA"))
    h = np.array(height_l.convert("L"))
    if h.shape[:2] != src.shape[:2]:
        raise ValueError(
            f"height {h.shape[1]}x{h.shape[0]} != source {src.shape[1]}x{src.shape[0]}"
        )
    h[void_mask_rgba(src)] = 0
    return Image.fromarray(h, mode="L")


def resize_to_source(generated: Image.Image, source_size: tuple[int, int]) -> Image.Image:
    height = generated.convert("L")
    if height.size != source_size:
        height = height.resize(source_size, _resample_filter())
    return height


def _gradient_mag(image: Image.Image) -> np.ndarray:
    grey = np.asarray(image.convert("L"), dtype=np.float32)
    dx = cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3)
    dy = cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(dx, dy)


def measure_registration(
    source: Image.Image,
    height: Image.Image,
    *,
    max_shift_px: int = QC_MAX_SHIFT_PX,
    min_response: float = QC_MIN_RESPONSE,
) -> dict[str, Any]:
    """Phase-correlate gradient magnitude of source luma vs the height field."""
    if source.size != height.size:
        raise ValueError(
            f"source {source.size} != height {height.size}; resize before QC"
        )
    sent = _gradient_mag(source)
    returned = _gradient_mag(height)
    info: dict[str, Any] = {
        "dx": 0,
        "dy": 0,
        "response": 0.0,
        "ok": False,
        "max_shift_px": int(max_shift_px),
        "min_response": float(min_response),
    }
    if min(sent.shape) < 8:
        info["reason"] = "image too small to register"
        return info
    (shift_x, shift_y), response = cv2.phaseCorrelate(sent, returned)
    dx, dy = int(round(shift_x)), int(round(shift_y))
    info["dx"] = dx
    info["dy"] = dy
    info["response"] = round(float(response), 4)
    if max(abs(dx), abs(dy)) > int(max_shift_px):
        info["reason"] = f"shift {dx},{dy} exceeds {max_shift_px}px"
        return info
    if float(response) < float(min_response):
        info["reason"] = f"response {response:.4f} below {min_response}"
        return info
    info["ok"] = True
    return info


def write_preview(
    source: Image.Image,
    height: Image.Image,
    dest: Path,
    *,
    punch: bool = True,
) -> None:
    src_rgb = source.convert("RGB")
    shown = punch_void(height, source) if punch else height.convert("L")
    right = Image.merge("RGB", (shown, shown, shown))
    if src_rgb.size != right.size:
        raise ValueError("preview sides must match")
    preview = Image.new("RGB", (src_rgb.width + right.width, src_rgb.height))
    preview.paste(src_rgb, (0, 0))
    preview.paste(right, (src_rgb.width, 0))
    dest.parent.mkdir(parents=True, exist_ok=True)
    preview.save(dest)


def align_generated(
    generated_path: Path,
    source_path: Path,
    *,
    height_out: Path,
    preview_out: Path | None = None,
    max_shift_px: int = QC_MAX_SHIFT_PX,
    min_response: float = QC_MIN_RESPONSE,
) -> dict[str, Any]:
    with Image.open(source_path) as src:
        source = src.convert("RGBA")
        source_size = source.size
    with Image.open(generated_path) as gen:
        aligned = resize_to_source(gen, source_size)
    height_out.parent.mkdir(parents=True, exist_ok=True)
    aligned.save(height_out)
    qc = measure_registration(
        source, aligned, max_shift_px=max_shift_px, min_response=min_response
    )
    qc["height_size"] = list(aligned.size)
    qc["source_size"] = list(source_size)
    if preview_out is not None:
        write_preview(source, aligned, preview_out, punch=True)
        qc["preview"] = str(preview_out)
    return qc
