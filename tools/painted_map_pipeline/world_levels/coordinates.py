from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .models import CanvasConfig, LevelSpec, LevelTransform, Point


class ScaledSpace:
    def __init__(self, scale: str | int | float):
        self.scale = Decimal(str(scale))
        if self.scale <= 0:
            raise ValueError("scale must be positive")

    def coordinate(self, value: int) -> int:
        return int((Decimal(value) * self.scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    def point(self, point: Point) -> Point:
        return self.coordinate(point[0]), self.coordinate(point[1])

    def span(self, origin: int, length: int) -> int:
        return self.coordinate(origin + length) - self.coordinate(origin)


def resolve_canvas(
    canvas: CanvasConfig,
    levels: dict[str, LevelSpec],
    scaled: ScaledSpace,
) -> tuple[int, int]:
    max_width = max(scaled.span(level.crop_x, level.crop_width) for level in levels.values())
    max_height = max(scaled.span(level.crop_y, level.crop_height) for level in levels.values())
    if canvas.mode == "derived":
        return max_width + 2 * canvas.margin, max_height + 2 * canvas.margin
    assert canvas.width is not None and canvas.height is not None
    if canvas.width < max_width + 2 * canvas.margin or canvas.height < max_height + 2 * canvas.margin:
        raise ValueError(
            f"configured canvas {canvas.width}x{canvas.height} cannot fit the largest scaled crop "
            f"{max_width}x{max_height} with margin {canvas.margin}"
        )
    return canvas.width, canvas.height


def build_transform(
    level: LevelSpec,
    scaled: ScaledSpace,
    canvas: CanvasConfig,
    canvas_size: tuple[int, int],
) -> LevelTransform:
    crop_left = scaled.coordinate(level.crop_x)
    crop_top = scaled.coordinate(level.crop_y)
    crop_width = scaled.span(level.crop_x, level.crop_width)
    crop_height = scaled.span(level.crop_y, level.crop_height)
    if canvas.placement == "center":
        offset_x = (canvas_size[0] - crop_width) // 2
        offset_y = (canvas_size[1] - crop_height) // 2
    else:
        offset_x = canvas.margin
        offset_y = canvas.margin
    if (
        offset_x < 0
        or offset_y < 0
        or offset_x + crop_width > canvas_size[0]
        or offset_y + crop_height > canvas_size[1]
    ):
        raise ValueError(f"level {level.level_id} does not fit the configured canvas")
    return LevelTransform(
        scale=str(scaled.scale),
        scaled_crop_left=crop_left,
        scaled_crop_top=crop_top,
        scaled_crop_width=crop_width,
        scaled_crop_height=crop_height,
        canvas_offset_x=offset_x,
        canvas_offset_y=offset_y,
        canvas_width=canvas_size[0],
        canvas_height=canvas_size[1],
    )


def polygon_to_local(
    polygon: tuple[Point, ...],
    scaled: ScaledSpace,
    transform: LevelTransform,
) -> tuple[Point, ...]:
    return tuple(transform.global_to_local(*scaled.point(point)) for point in polygon)
