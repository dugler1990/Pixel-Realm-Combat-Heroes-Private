"""Fit AI-generated land art onto the template land silhouette via outline warp."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image
from scipy.interpolate import RBFInterpolator
from scipy.ndimage import distance_transform_edt, map_coordinates


def _largest_contour(mask: np.ndarray) -> np.ndarray:
    u8 = np.ascontiguousarray(mask.astype(np.uint8) * 255)
    contours, _ = cv2.findContours(u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("land mask has no contours")
    return max(contours, key=cv2.contourArea)


def _centroid(contour: np.ndarray) -> tuple[float, float]:
    moments = cv2.moments(contour)
    if moments["m00"] == 0:
        raise ValueError("degenerate land contour")
    return moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]


def sample_radial_outline(mask: np.ndarray, count: int) -> tuple[np.ndarray, tuple[float, float]]:
    """Sample outline points at evenly spaced angles from the land centroid."""
    if count < 8:
        raise ValueError("outline sample count must be at least 8")
    contour = _largest_contour(mask)
    points = contour.reshape(-1, 2).astype(np.float64)
    cx, cy = _centroid(contour)
    angles = np.arctan2(points[:, 1] - cy, points[:, 0] - cx)
    distances = np.hypot(points[:, 0] - cx, points[:, 1] - cy)
    targets = np.linspace(-np.pi, np.pi, count, endpoint=False)
    half_bin = np.pi / count
    sampled = np.zeros((count, 2), dtype=np.float64)
    for index, target in enumerate(targets):
        delta = np.abs(np.arctan2(np.sin(angles - target), np.cos(angles - target)))
        in_bin = delta <= half_bin
        if np.any(in_bin):
            members = np.flatnonzero(in_bin)
            sampled[index] = points[members[np.argmax(distances[members])]]
        else:
            sampled[index] = points[int(np.argmin(delta))]
    return sampled, (cx, cy)


def fit_generated_to_mask(
    generated: Image.Image,
    generation_mask: Image.Image,
    *,
    outside_color: tuple[int, int, int, int],
    content_luma_threshold: int = 40,
    outline_samples: int = 96,
    rbf_smoothing: float = 1.0,
) -> Image.Image:
    """
    Warp generated land so its outline matches generation_mask.

    Source land = non-black pixels on generated. Target land = generation_mask.
    Control points are angle-matched outline samples plus centroids; a thin-plate
    RBF maps each target land pixel back to a source sample location.
    """
    canvas = generated.convert("RGBA")
    expected_size = canvas.size
    mask = np.asarray(generation_mask.convert("L")) > 0
    if mask.shape != (expected_size[1], expected_size[0]):
        raise ValueError(
            f"generation mask size {mask.shape[1]}x{mask.shape[0]} "
            f"does not match canvas {expected_size[0]}x{expected_size[1]}"
        )
    if not np.any(mask):
        raise ValueError("generation mask is empty")

    pixels = np.asarray(canvas)
    content = pixels[:, :, :3].sum(axis=2) > content_luma_threshold
    if not np.any(content):
        raise ValueError("generated image has no non-black content to fit")

    source_outline, source_center = sample_radial_outline(content, outline_samples)
    target_outline, target_center = sample_radial_outline(mask, outline_samples)
    source_controls = np.vstack([source_outline, np.asarray(source_center, dtype=np.float64)])
    target_controls = np.vstack([target_outline, np.asarray(target_center, dtype=np.float64)])

    # Inverse map: target pixel -> source sample coordinate.
    mapper = RBFInterpolator(
        target_controls,
        source_controls,
        kernel="thin_plate_spline",
        smoothing=rbf_smoothing,
    )

    target_ys, target_xs = np.where(mask)
    query = np.column_stack([target_xs, target_ys]).astype(np.float64)
    source_xy = mapper(query)
    sample_rows = source_xy[:, 1]
    sample_cols = source_xy[:, 0]

    source = pixels.astype(np.float32)
    fitted = np.zeros_like(pixels)
    fitted[:, :] = np.asarray(outside_color, dtype=np.uint8)
    for channel in range(4):
        sampled = map_coordinates(
            source[:, :, channel],
            [sample_rows, sample_cols],
            order=1,
            mode="constant",
            cval=float(outside_color[channel]),
        )
        fitted[target_ys, target_xs, channel] = np.clip(np.rint(sampled), 0, 255).astype(np.uint8)

    # Fill tiny holes where the warp sampled empty source inside the target land.
    land = fitted[:, :, :3].sum(axis=2) > content_luma_threshold
    holes = mask & ~land
    if np.any(holes) and np.any(land):
        _, (nearest_y, nearest_x) = distance_transform_edt(~land, return_indices=True)
        fitted[holes] = fitted[nearest_y[holes], nearest_x[holes]]

    return Image.fromarray(fitted, mode="RGBA")
