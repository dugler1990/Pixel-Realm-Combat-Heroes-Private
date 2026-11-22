"""Still water in a hole, drawn on the test-suite arena floor.

`flat` is a circle the water fills. `pit` is the beach: the same ground at 45°,
a short near wall you could wade down. `cliff` keeps that opening, but the side
toward the hero is a tall face and the water sits at the foot of it.
`cube` is an isometric rectangular pit: a diamond mouth, four inner walls,
water on the floor. The tall face is the cliff toward the hero.
`shaft` is that same box with the walls vertical. No motion.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

ELEVATION_DEG = 45.0

WATER_RGB = (42, 112, 176)
GROUND_RGB = (86, 92, 98)
WALL_RGB = (46, 52, 58)
FAR_WALL_RGB = (72, 80, 88)
RIM_RGB = (28, 30, 34)
FAR_RIM_RGB = (168, 176, 184)
NEAR_RIM_RGB = (18, 20, 22)

STYLES = ("flat", "pit", "cliff", "cube", "shaft")
# Beach only. The cliff is a face with a waterline, not a smaller copy of this.
_PIT = {"pit": (0.72, 0.55)}
# Share of the opening's half-height: waterline sits this far below the centre,
# so the face toward the hero is most of the hole.
_CLIFF_WATERLINE = 0.45
SLAB = (560, 400)
HOLE_RADIUS = 120


@dataclass(frozen=True)
class Ellipse:
    cx: float
    cy: float
    rx: float
    ry: float

    def contains(self, x: float, y: float) -> bool:
        if self.rx <= 0 or self.ry <= 0:
            return False
        dx = (x - self.cx) / self.rx
        dy = (y - self.cy) / self.ry
        return dx * dx + dy * dy <= 1.0

    def point_at(self, turns: float) -> tuple[float, float]:
        angle = turns * math.tau
        return (
            self.cx + self.rx * math.cos(angle),
            self.cy + self.ry * math.sin(angle),
        )


@dataclass(frozen=True)
class CubeCut:
    """Isometric pit. Rim and floor are N, E, S, W in screen space."""

    cx: float
    cy: float
    rim: tuple
    floor: tuple


@dataclass(frozen=True)
class HoleLayout:
    style: str
    opening: Ellipse
    water: Ellipse
    waterline: float | None = None
    cube: CubeCut | None = None

    @property
    def far_wall(self) -> float:
        if self.waterline is not None:
            return self.waterline - (self.opening.cy - self.opening.ry)
        return (self.water.cy - self.water.ry) - (self.opening.cy - self.opening.ry)

    @property
    def near_wall(self) -> float:
        if self.waterline is not None:
            return (self.opening.cy + self.opening.ry) - self.waterline
        return (self.opening.cy + self.opening.ry) - (self.water.cy + self.water.ry)


def layout_at(style: str, cx: float, cy: float, radius: float) -> HoleLayout:
    if style not in STYLES:
        raise ValueError(style)
    if style == "flat":
        opening = Ellipse(cx, cy, radius, radius)
        return HoleLayout(style, opening, opening)
    if style == "cube":
        return _cube_layout(cx, cy, radius)
    if style == "shaft":
        return _shaft_layout(cx, cy, radius)
    rx = radius
    ry = rx * math.sin(math.radians(ELEVATION_DEG))
    opening = Ellipse(cx, cy, rx, ry)
    if style == "cliff":
        waterline = cy + ry * _CLIFF_WATERLINE
        water_ry = ((cy + ry) - waterline) / 2
        water = Ellipse(cx, waterline + water_ry, rx * 0.5, water_ry)
        return HoleLayout(style, opening, water, waterline)
    water_scale, shift_frac = _PIT[style]
    water_rx = rx * water_scale
    water_ry = ry * water_scale
    shift = (ry - water_ry) * shift_frac
    water = Ellipse(cx, cy + shift, water_rx, water_ry)
    return HoleLayout(style, opening, water)


def _iso_rim(cx: float, cy: float, radius: float):
    """Square on the ground, turned 45° so the pit shows its corner."""
    v = radius * 0.95
    hw = v * math.sqrt(2.0)
    return (
        (cx, cy - v),
        (cx + hw, cy),
        (cx, cy + v),
        (cx - hw, cy),
    )


def _cube_layout(cx: float, cy: float, radius: float) -> HoleLayout:
    """Rectangular box cut into the ground. Floor sits inside the mouth, shifted down."""
    rim = _iso_rim(cx, cy, radius)
    scale, shift = 0.48, (rim[2][1] - rim[0][1]) * 0.11
    floor = tuple(
        (cx + (x - cx) * scale, cy + (y - cy) * scale + shift) for x, y in rim
    )
    v = rim[2][1] - cy
    hw = rim[1][0] - cx
    cut = CubeCut(cx, cy, rim, floor)
    return HoleLayout("cube", Ellipse(cx, cy, hw, v), Ellipse(cx, cy + shift, hw * scale, v * scale), cube=cut)


def _shaft_layout(cx: float, cy: float, radius: float) -> HoleLayout:
    """Same diamond mouth as the sloped box. Each floor corner is straight under its rim corner."""
    v = radius * 0.62
    hw = v * math.sqrt(2.0)
    rim = (
        (cx, cy - v),
        (cx + hw, cy),
        (cx, cy + v),
        (cx - hw, cy),
    )
    drop = v * 0.75
    floor = tuple((x, y + drop) for x, y in rim)
    cut = CubeCut(cx, cy, rim, floor)
    return HoleLayout("shaft", Ellipse(cx, cy, hw, v), Ellipse(cx, cy + drop, hw, v), cube=cut)


def layout_for(style: str, width: int, height: int) -> HoleLayout:
    radius = min(width, height) * (0.30 if style == "flat" else 0.36)
    return layout_at(style, width * 0.5, height * 0.54, radius)


def _metric(xx, yy, ellipse: Ellipse):
    return ((xx - ellipse.cx) / ellipse.rx) ** 2 + ((yy - ellipse.cy) / ellipse.ry) ** 2


def _poly_mask(height: int, width: int, pts) -> np.ndarray:
    mask = np.zeros((height, width), dtype=bool)
    n = len(pts)
    y0 = max(0, int(math.floor(min(y for _, y in pts))))
    y1 = min(height - 1, int(math.ceil(max(y for _, y in pts))))
    for y in range(y0, y1 + 1):
        yscan = y + 0.5
        nodes = []
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if (y1 <= yscan < y2) or (y2 <= yscan < y1):
                nodes.append(x1 + (yscan - y1) * (x2 - x1) / (y2 - y1))
        nodes.sort()
        for i in range(0, len(nodes) - 1, 2):
            x_start = max(0, int(math.ceil(nodes[i])))
            x_end = min(width - 1, int(math.floor(nodes[i + 1])))
            if x_start <= x_end:
                mask[y, x_start:x_end + 1] = True
    return mask


def _paint(layer, mask, rgb):
    layer[mask, :3] = rgb
    layer[mask, 3] = 255


def _compose_cube(layout: HoleLayout, width: int, height: int):
    cut = layout.cube
    rim = cut.rim
    floor = cut.floor
    # The vertical shaft hangs below the diamond, so the ground opens around that whole silhouette.
    mouth_pts = rim if layout.style == "cube" else (
        rim[0], rim[1], floor[1], floor[2], floor[3], rim[3]
    )
    mouth = _poly_mask(height, width, mouth_pts)
    pool = _poly_mask(height, width, floor)
    # N-E, E-S, S-W, W-N. Light on the hero side, darker on the near side.
    faces = (
        (rim[0], rim[1], floor[1], floor[0], (176, 184, 192)),
        (rim[1], rim[2], floor[2], floor[1], (72, 78, 86)),
        (rim[2], rim[3], floor[3], floor[2], (28, 30, 34)),
        (rim[3], rim[0], floor[0], floor[3], (118, 126, 136)),
    )

    noise = np.random.default_rng(1).integers(-10, 11, size=(height, width), dtype=np.int16)
    ground = np.empty((height, width, 4), dtype=np.uint8)
    ground[..., :3] = np.clip(
        np.array(GROUND_RGB, dtype=np.int16) + noise[..., None], 0, 255
    ).astype(np.uint8)
    ground[..., 3] = np.where(mouth, 0, 255).astype(np.uint8)

    wall = np.zeros((height, width, 4), dtype=np.uint8)
    for a, b, c, d, rgb in faces:
        _paint(wall, _poly_mask(height, width, (a, b, c, d)) & mouth & ~pool, rgb)
    water = np.zeros((height, width, 4), dtype=np.uint8)
    _paint(water, pool & mouth, WATER_RGB)
    return ground, water, wall


def compose(layout: HoleLayout, width: int, height: int):
    """Ground, water, and pit wall as RGBA arrays. Built once; nothing here animates."""
    if layout.style in ("cube", "shaft"):
        return _compose_cube(layout, width, height)
    yy, xx = np.ogrid[:height, :width]
    opening_m = _metric(xx, yy, layout.opening)
    water_m = _metric(xx, yy, layout.water)
    inside_opening = opening_m <= 1.0
    inside_water = water_m <= 1.0

    noise = np.random.default_rng(1).integers(-10, 11, size=(height, width), dtype=np.int16)
    ground = np.empty((height, width, 4), dtype=np.uint8)
    ground[..., :3] = np.clip(
        np.array(GROUND_RGB, dtype=np.int16) + noise[..., None], 0, 255
    ).astype(np.uint8)
    ground[..., 3] = np.where(inside_opening, 0, 255).astype(np.uint8)

    eps = 5.0 / min(layout.opening.rx, layout.opening.ry)
    rim = (opening_m > 1.0) & (opening_m <= (1.0 + eps) ** 2)
    ground[rim, :3] = RIM_RGB
    if layout.style != "flat":
        ground[rim & (yy < layout.opening.cy), :3] = FAR_RIM_RGB
        ground[rim & (yy >= layout.opening.cy), :3] = NEAR_RIM_RGB

    water = np.zeros((height, width, 4), dtype=np.uint8)
    wall = np.zeros((height, width, 4), dtype=np.uint8)
    if layout.style == "cliff":
        inside_water = inside_opening & (yy >= layout.waterline)
        face = inside_opening & (yy < layout.waterline)
        top = layout.opening.cy - layout.opening.ry
        span = max(layout.waterline - top, 1.0)
        shade = np.clip((np.arange(height) - top) / span, 0.0, 1.0)
        lit = np.array((168, 174, 180), dtype=np.float32)
        dark = np.array((16, 18, 22), dtype=np.float32)
        colour = (lit * (1.0 - shade[:, None]) + dark * shade[:, None]).astype(np.uint8)
        wall[..., :3] = colour[:, None, :]
        wall[..., 3] = np.where(face, 255, 0).astype(np.uint8)
        lip = (opening_m > 1.0) & (opening_m <= (1.0 + eps * 2.4) ** 2) & (yy < layout.waterline)
        ground[lip, :3] = FAR_RIM_RGB
    elif layout.style == "pit":
        band = inside_opening & ~inside_water
        wall[band, :3] = WALL_RGB
        wall[band & (yy < layout.water.cy), :3] = FAR_WALL_RGB
        wall[band, 3] = 255

    water[inside_water, :3] = WATER_RGB
    water[inside_water, 3] = 255
    return ground, water, wall


def _surface_from_rgba(array):
    import pygame

    height, width = array.shape[:2]
    raw = np.ascontiguousarray(array)
    return pygame.image.frombuffer(raw.tobytes(), (width, height), "RGBA").convert_alpha()


class FloorHole:
    """A stone slab with a still hole, drawn on the black arena floor."""

    def __init__(self):
        self.style = "flat"
        self.draw_ms = 0.0
        self._center = (0.0, 0.0)
        self._layers = None
        self._origin = (0, 0)

    def place(self, world_x: float, world_y: float):
        self._center = (float(world_x), float(world_y))
        self.rebuild()

    def set_style(self, style: str):
        if style not in STYLES or style == self.style:
            return
        self.style = style
        self.rebuild()

    def rebuild(self):
        width, height = SLAB
        layout = layout_at(self.style, width / 2, height / 2, HOLE_RADIUS)
        ground, water, wall = compose(layout, width, height)
        self._layers = (
            _surface_from_rgba(ground),
            _surface_from_rgba(water),
            _surface_from_rgba(wall),
        )
        self._origin = (int(self._center[0] - width / 2), int(self._center[1] - height / 2))

    def draw(self, camera):
        if self._layers is None:
            return
        ground, water, wall = self._layers
        ox = self._origin[0] - camera.offset.x
        oy = self._origin[1] - camera.offset.y
        if self.style != "flat":
            camera.backend.blit(wall, (ox, oy), cache_key=id(wall))
        started = time.perf_counter()
        camera.backend.blit(water, (ox, oy), cache_key=id(water))
        self.draw_ms = (time.perf_counter() - started) * 1000.0
        camera.backend.blit(ground, (ox, oy), cache_key=id(ground))
