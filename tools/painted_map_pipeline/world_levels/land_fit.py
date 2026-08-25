"""Fit AI-generated land art onto the template land silhouette via outline warp."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image
from scipy.interpolate import RBFInterpolator
from scipy.ndimage import binary_erosion, distance_transform_edt, map_coordinates

_RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)


# Summed RGB above which a pixel counts as painted rather than background. Every measurement
# of "where the art is" uses this one number, so a picture of an error and the score for it
# cannot disagree about which pixels are involved.
CONTENT_LUMA_THRESHOLD = 40


def footprint_iou(
    generated: Image.Image,
    generation_mask: Image.Image,
    *,
    content_luma_threshold: int = CONTENT_LUMA_THRESHOLD,
) -> float:
    """IoU between the generated land footprint and the template silhouette.

    Measured on the raw generation, before any warp. This is the number that
    distinguishes a faithful repaint from a reframed one: a model that re-crops the
    reference to its content bbox scores ~0.2 here while still warping cleanly.
    """
    pixels = np.asarray(generated.convert("RGBA"))
    content = pixels[:, :, :3].sum(axis=2) > content_luma_threshold
    mask = np.asarray(generation_mask.convert("L")) > 0
    if content.shape != mask.shape:
        raise ValueError(
            f"generated size {content.shape[1]}x{content.shape[0]} does not match "
            f"generation mask {mask.shape[1]}x{mask.shape[0]}"
        )
    union = np.count_nonzero(content | mask)
    if union == 0:
        return 0.0
    return float(np.count_nonzero(content & mask) / union)


def _content_mask(generated: Image.Image, content_luma_threshold: int) -> np.ndarray:
    pixels = np.asarray(generated.convert("RGBA"))
    return pixels[:, :, :3].sum(axis=2) > content_luma_threshold


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        raise ValueError("mask is empty")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def content_bbox(
    generated: Image.Image,
    *,
    content_luma_threshold: int = CONTENT_LUMA_THRESHOLD,
) -> tuple[int, int, int, int]:
    """Bounding box of the painted region, as (x0, y0, x1, y1).

    Uses the largest connected component rather than a raw non-black bbox: a handful
    of stray lit pixels in a corner would otherwise stretch the box to the whole canvas
    and wreck the rescale factors. Same guard as ``_largest_contour`` applies to the warp.
    """
    content = _content_mask(generated, content_luma_threshold)
    if not np.any(content):
        raise ValueError("generated image has no non-black content")
    count, _, stats, _ = cv2.connectedComponentsWithStats(
        np.ascontiguousarray(content.astype(np.uint8)), connectivity=8
    )
    if count <= 1:
        return _bbox(content)
    # Row 0 is the background component; pick the largest of the rest by area.
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x = int(stats[largest, cv2.CC_STAT_LEFT])
    y = int(stats[largest, cv2.CC_STAT_TOP])
    return x, y, x + int(stats[largest, cv2.CC_STAT_WIDTH]), y + int(stats[largest, cv2.CC_STAT_HEIGHT])


def is_full_bleed(
    generated: Image.Image,
    *,
    content_luma_threshold: int = CONTENT_LUMA_THRESHOLD,
    min_black_fraction: float = 0.02,
) -> bool:
    """True when the render has essentially no black left, so there is no land outline.

    Nothing can be recovered from this: the warp ends up tracing the canvas rectangle as
    if it were a coastline. Note this deliberately does *not* test whether paint reaches
    the canvas borders — a render that was cropped to its content and stretched to fill
    the frame touches all four borders by construction, and that case rescales fine.
    """
    content = _content_mask(generated, content_luma_threshold)
    if not np.any(content):
        return False
    return bool((~content).mean() < min_black_fraction)


def rescale_to_mask(
    generated: Image.Image,
    generation_mask: Image.Image,
    *,
    outside_color: tuple[int, int, int, int] = (0, 0, 0, 255),
    content_luma_threshold: int = CONTENT_LUMA_THRESHOLD,
) -> tuple[Image.Image, dict]:
    """Squash a reframed render back onto the template silhouette's bounding box.

    Models routinely discard the black letterbox and render the land to fill the frame.
    The correction is deterministic — the destination box is known exactly from
    ``generation_mask.png`` — so this is a straight resize, not a fitted search. x and y
    scale independently because the land bbox aspect rarely matches the canvas aspect.
    """
    source = content_bbox(generated, content_luma_threshold=content_luma_threshold)
    mask = np.asarray(generation_mask.convert("L")) > 0
    if not np.any(mask):
        raise ValueError("generation mask is empty")
    target = _bbox(mask)

    source_w, source_h = source[2] - source[0], source[3] - source[1]
    target_w, target_h = target[2] - target[0], target[3] - target[1]

    canvas = Image.new("RGBA", generated.size, outside_color)
    patch = generated.convert("RGBA").crop(source).resize((target_w, target_h), _RESAMPLE)
    canvas.paste(patch, (target[0], target[1]))
    info = {
        "scale_x": round(target_w / source_w, 4),
        "scale_y": round(target_h / source_h, 4),
        "source_bbox": list(source),
        "target_bbox": list(target),
    }
    return canvas, info


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


def cut_to_mask(
    generated: Image.Image,
    generation_mask: Image.Image,
    *,
    outside_color: tuple[int, int, int, int],
) -> Image.Image:
    """Keep what landed inside the polygon, discard what spilled past it. No deformation.

    The blunt sibling of ``fit_generated_to_mask``. That one drags the outline onto the mask
    by warping the whole picture, which moves every feature in it -- worth it only when the
    return is genuinely the wrong shape.

    Once the API mask is sent with the polarity the model actually obeys, it is not: the error
    collapses to a soft fringe at the boundary -- measured on level 02, 95% of disagreeing
    pixels within 25px of the edge, and mostly overshoot. Trimming a fringe needs no warp, and
    a cut cannot invent the shortfall, so it is honest about what it does not fix.
    """
    canvas = generated.convert("RGBA")
    mask = generation_mask.convert("L")
    if mask.size != canvas.size:
        raise ValueError(
            f"generation mask size {mask.size[0]}x{mask.size[1]} "
            f"does not match canvas {canvas.size[0]}x{canvas.size[1]}"
        )
    return Image.composite(canvas, Image.new("RGBA", canvas.size, outside_color), mask)


def fit_generated_to_mask(
    generated: Image.Image,
    generation_mask: Image.Image,
    *,
    outside_color: tuple[int, int, int, int],
    content_luma_threshold: int = CONTENT_LUMA_THRESHOLD,
    outline_samples: int = 96,
    rbf_smoothing: float = 1.0,
    edge_trim: int = 3,
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

    # Sample the interior only. Pixels on the mask boundary map to source coordinates at
    # or just past the edge of the generated content, so bilinear sampling mixes them
    # with the black surround and leaves a dark rim -- measured at luminance 110 against
    # an interior of 167 on level 04. That rim then gets carried into every neighbour as
    # padding and reads as a hard scar. The rim is filled from its nearest interior
    # neighbour below, so the full mask is still covered and levels still tile exactly.
    interior = mask
    if edge_trim > 0:
        eroded = binary_erosion(mask, np.ones((edge_trim * 2 + 1,) * 2))
        if np.any(eroded):
            interior = eroded

    target_ys, target_xs = np.where(interior)
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

    # Cover the untouched rim, plus any hole where the warp sampled empty source, from
    # the nearest painted interior pixel. The whole mask ends up filled either way.
    land = np.zeros(mask.shape, dtype=bool)
    land[target_ys, target_xs] = fitted[target_ys, target_xs, :3].sum(axis=1) > content_luma_threshold
    holes = mask & ~land
    if np.any(holes) and np.any(land):
        _, (nearest_y, nearest_x) = distance_transform_edt(~land, return_indices=True)
        fitted[holes] = fitted[nearest_y[holes], nearest_x[holes]]

    return Image.fromarray(fitted, mode="RGBA")
