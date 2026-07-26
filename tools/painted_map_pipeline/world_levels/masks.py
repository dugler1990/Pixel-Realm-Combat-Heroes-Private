from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from .coordinates import ScaledSpace, polygon_to_local
from .models import LevelSpec, LevelTransform, OverlapRaster, Point


def rasterize_polygon(size: tuple[int, int], points: tuple[Point, ...]) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def build_level_masks(
    level: LevelSpec,
    scaled: ScaledSpace,
    transform: LevelTransform,
) -> tuple[Image.Image, Image.Image]:
    size = (transform.canvas_width, transform.canvas_height)
    core = rasterize_polygon(size, polygon_to_local(level.core_polygon, scaled, transform))
    generation = rasterize_polygon(size, polygon_to_local(level.generation_polygon, scaled, transform))
    core_array = np.asarray(core) > 0
    generation_array = np.asarray(generation) > 0
    if np.any(core_array & ~generation_array):
        raise ValueError(f"level {level.level_id}: core polygon is not contained by generation polygon")
    return core, generation


def _global_polygon_raster(
    polygon: tuple[Point, ...],
    scaled: ScaledSpace,
    box: tuple[int, int, int, int],
) -> Image.Image:
    points = tuple((scaled.coordinate(x) - box[0], scaled.coordinate(y) - box[1]) for x, y in polygon)
    return rasterize_polygon((box[2] - box[0], box[3] - box[1]), points)


def compute_overlap(
    first: LevelSpec,
    second: LevelSpec,
    scaled: ScaledSpace,
) -> OverlapRaster | None:
    first_points = tuple(scaled.point(point) for point in first.generation_polygon)
    second_points = tuple(scaled.point(point) for point in second.generation_polygon)
    left = max(min(point[0] for point in first_points), min(point[0] for point in second_points))
    top = max(min(point[1] for point in first_points), min(point[1] for point in second_points))
    right = min(max(point[0] for point in first_points), max(point[0] for point in second_points)) + 1
    bottom = min(max(point[1] for point in first_points), max(point[1] for point in second_points)) + 1
    if right <= left or bottom <= top:
        return None
    box = (left, top, right, bottom)
    first_mask = np.asarray(_global_polygon_raster(first.generation_polygon, scaled, box)) > 0
    second_mask = np.asarray(_global_polygon_raster(second.generation_polygon, scaled, box)) > 0
    overlap = first_mask & second_mask
    if not np.any(overlap):
        return None
    return OverlapRaster(box, (overlap.astype(np.uint8) * 255))


def overlap_on_canvas(overlap: OverlapRaster, transform: LevelTransform) -> Image.Image:
    canvas = Image.new("L", (transform.canvas_width, transform.canvas_height), 0)
    x, y = transform.global_to_local(overlap.global_box[0], overlap.global_box[1])
    source = Image.fromarray(overlap.pixels, mode="L")
    canvas.paste(source, (x, y), source)
    return canvas


def pending_mask(generation: Image.Image, locked: Image.Image) -> Image.Image:
    generation_array = np.asarray(generation) > 0
    locked_array = np.asarray(locked) > 0
    return Image.fromarray(((generation_array & ~locked_array).astype(np.uint8) * 255), mode="L")


def outside_mask(generation: Image.Image) -> Image.Image:
    return Image.fromarray((~(np.asarray(generation) > 0)).astype(np.uint8) * 255, mode="L")
