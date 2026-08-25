"""Vertex-space polygon geometry — the single home for math that was previously
inlined/duplicated across the pipeline.

The vertex helpers (``orientation``, ``on_segment``, ``segments_intersect``,
``validate_simple_polygon``) are lifted verbatim from ``plan_loader.py`` so both the
plan loader and the sub-level splitter share one implementation. The raster↔vertex
helpers (``mask_to_polygon``, ``largest_connected_component``) support the splitter,
which proposes regions as pixel masks and must emit them as polygons.

Kept dependency-light: numpy + cv2 (already pipeline deps) and the ``Point`` alias.
No PIL, no coordinates — polygon→raster stays in ``masks.rasterize_polygon`` (its
single home); this module only does raster→polygon.
"""

from __future__ import annotations

import cv2
import numpy as np

from .models import Point


# --------------------------------------------------------------------------- #
# Vertex-space primitives (lifted from plan_loader; behavior identical)
# --------------------------------------------------------------------------- #
def orientation(a: Point, b: Point, c: Point) -> int:
    value = (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])
    return 0 if value == 0 else (1 if value > 0 else -1)


def on_segment(a: Point, b: Point, c: Point) -> bool:
    return min(a[0], c[0]) <= b[0] <= max(a[0], c[0]) and min(a[1], c[1]) <= b[1] <= max(a[1], c[1])


def segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    o1, o2, o3, o4 = orientation(a, b, c), orientation(a, b, d), orientation(c, d, a), orientation(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and on_segment(a, c, b))
        or (o2 == 0 and on_segment(a, d, b))
        or (o3 == 0 and on_segment(c, a, d))
        or (o4 == 0 and on_segment(c, b, d))
    )


def polygon_area(points: tuple[Point, ...]) -> float:
    """Unsigned polygon area via the shoelace formula."""
    count = len(points)
    if count < 3:
        return 0.0
    area2 = sum(
        points[index][0] * points[(index + 1) % count][1]
        - points[(index + 1) % count][0] * points[index][1]
        for index in range(count)
    )
    return abs(area2) / 2.0


def _self_intersects(points: tuple[Point, ...]) -> bool:
    count = len(points)
    for first in range(count):
        a, b = points[first], points[(first + 1) % count]
        for second in range(first + 1, count):
            if second in {first, (first + 1) % count} or (second + 1) % count == first:
                continue
            c, d = points[second], points[(second + 1) % count]
            if segments_intersect(a, b, c, d):
                return True
    return False


def validate_simple_polygon(points: tuple[Point, ...], field: str, level_id: str) -> None:
    """Raise ValueError if the polygon has zero area or self-intersects.

    Preserves the exact messages and behavior of the former
    ``plan_loader._validate_simple_polygon``.
    """
    count = len(points)
    area2 = sum(
        points[index][0] * points[(index + 1) % count][1]
        - points[(index + 1) % count][0] * points[index][1]
        for index in range(count)
    )
    if area2 == 0:
        raise ValueError(f"level {level_id}: {field} has zero area")
    if _self_intersects(points):
        raise ValueError(f"level {level_id}: {field} self-intersects")


def polygon_bbox(points: tuple[Point, ...]) -> tuple[int, int, int, int]:
    """Axis-aligned bounding box (left, top, right, bottom), right/bottom exclusive-ish
    at the max vertex (callers add +1 or a margin as needed)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------------- #
# Raster → vertex (splitter support)
# --------------------------------------------------------------------------- #
def largest_connected_component(mask: np.ndarray) -> np.ndarray:
    """Return a boolean mask keeping only the largest connected component."""
    u8 = np.ascontiguousarray(mask.astype(np.uint8))
    num, labels = cv2.connectedComponents(u8, connectivity=8)
    if num <= 1:
        return mask.astype(bool)
    sizes = [(int(np.count_nonzero(labels == label)), label) for label in range(1, num)]
    _, keep = max(sizes)
    return labels == keep


def gradient_magnitude_mean(gray: np.ndarray, mask: np.ndarray, *, blur_sigma: float = 0.0) -> float:
    """Mean Sobel gradient magnitude over a mask -- a 'ruggedness' measure.

    With ``blur_sigma`` > 0 the image is Gaussian-blurred first, so fine surface texture (sand
    grain, ice floes) is smoothed away and only large-scale relief (actual mountain ranges) is
    measured -- the raw 3x3 gradient scores textured desert and choppy water as high as peaks.
    0.0 for an empty mask."""
    if not mask.any():
        return 0.0
    g = gray.astype(np.float32)
    if blur_sigma > 0:
        g = cv2.GaussianBlur(g, (0, 0), float(blur_sigma))
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return float(np.hypot(gx, gy)[mask].mean())


def dilate_mask(mask: np.ndarray, radius: int) -> np.ndarray:
    """Grow a boolean mask by ``radius`` pixels (elliptical kernel). radius<=0 is a no-op."""
    if radius <= 0:
        return mask.astype(bool)
    k = 2 * radius + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    return cv2.dilate(np.ascontiguousarray(mask.astype(np.uint8)), kernel) > 0


def mask_to_polygon(mask: np.ndarray, *, epsilon_frac: float = 0.01) -> tuple[Point, ...]:
    """Convert a boolean mask to a simplified polygon (largest external contour).

    Points are in the mask's own pixel frame; the caller offsets to world space.
    ``epsilon_frac`` is the Douglas-Peucker tolerance as a fraction of the contour
    perimeter. Raises ValueError if the mask has no usable contour.
    """
    solid = largest_connected_component(mask)
    u8 = np.ascontiguousarray(solid.astype(np.uint8) * 255)
    contours, _ = cv2.findContours(u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("mask has no contour to convert to a polygon")
    contour = max(contours, key=cv2.contourArea)
    epsilon = max(1.0, epsilon_frac * cv2.arcLength(contour, True))
    approx = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
    if len(approx) < 3:
        # Too aggressive a simplification; fall back to the raw hull.
        approx = cv2.convexHull(contour).reshape(-1, 2)
    # Drop consecutive duplicate vertices that approxPolyDP can leave behind.
    points: list[Point] = []
    for x, y in approx:
        pt = (int(x), int(y))
        if not points or points[-1] != pt:
            points.append(pt)
    if len(points) >= 2 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3:
        raise ValueError("mask polygon collapsed to fewer than three points")
    return tuple(points)
