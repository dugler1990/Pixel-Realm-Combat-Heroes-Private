"""Sample a painted-chunk heightmap in world pixels.

Void is not height 0: the PNG stores 0 on both the off-map void and legal low
ground. The land mask comes from the matching source.png.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from Settings import TILESIZE

GRADIENT_STEP_PX = 12
VOID_RGB_MAX = 12
VOID_ALPHA_MAX = 8

# chunk_00_01 in assembled-map pixels (x, y, w, h). Valid only while TILESIZE
# equals the TMX tile width (scale 1.0).
CHUNK_00_01_WORLD_RECT = (0, 3065, 4495, 3065)
CHUNK_00_01_RELATIVE = (
    "export/sam3_chunks/chunk_00_01/heightmap.png",
    "export/sam3_chunks/chunk_00_01/source.png",
)

# World-pixel goldens for this PNG (wx, wy) -> 0..255. Void is None.
GOLDEN_HEIGHT_U8 = {
    (2200, 4600): 189,  # ridge
    (1000, 3500): 216,  # high shelf
    (4000, 5900): 92,  # wash
}
GOLDEN_VOID = (50, 3100)
GOLDEN_RIDGE = (2200, 4600)
GOLDEN_SHELF = (1000, 3500)
GOLDEN_WASH = (4000, 5900)
HEIGHT_U8_TOLERANCE = 4

# Gravity along the slope: velocity += -G * gradient.
# Ridge |grad| ~0.00185 → force ~0.4 px/frame². Walk accel is 0.4, so ~20% of
# speed 5 at equilibrium (v = target + force/accel). A 1/5 wrinkle is ~4%.
PHYSICS_GRADIENT_STEP = 36
TERRAIN_G = 220.0
GRADE_DEADZONE = 0.0002
GRADE_SMOOTH = 0.4
HEIGHT_OVERLAY_ALPHA = 210


class ChunkHeightmap:
    def __init__(
        self,
        height_path: Path,
        source_path: Path,
        world_rect: tuple[int, int, int, int],
        *,
        world_scale: float = 1.0,
        gradient_step: int = GRADIENT_STEP_PX,
    ):
        if abs(float(world_scale) - 1.0) > 1e-6:
            raise ValueError(
                f"painted pixels are not world pixels: scale={world_scale}"
            )
        ox, oy, rw, rh = (int(v) for v in world_rect)
        with Image.open(height_path) as im:
            height = im.convert("L")
            hw, hh = height.size
            height_bytes = height.tobytes()
        if (hw, hh) != (rw, rh):
            raise ValueError(
                f"heightmap size {hw}x{hh} != world_rect {rw}x{rh}"
            )
        with Image.open(source_path) as im:
            source = im.convert("RGBA")
            sw, sh = source.size
            src_px = source.tobytes()
        if (sw, sh) != (rw, rh):
            raise ValueError(
                f"source size {sw}x{sh} != world_rect {rw}x{rh}"
            )
        rgba = np.frombuffer(src_px, dtype=np.uint8).reshape(hh, hw, 4)
        rgb_max = rgba[:, :, :3].max(axis=2)
        void = (rgba[:, :, 3] < VOID_ALPHA_MAX) | (rgb_max < VOID_RGB_MAX)
        self._height = np.frombuffer(height_bytes, dtype=np.uint8).reshape(hh, hw)
        self._void = void
        self.origin_x = ox
        self.origin_y = oy
        self.width = rw
        self.height_px = rh
        self.gradient_step = int(gradient_step)

    def _local(self, wx: float, wy: float) -> Optional[tuple[int, int]]:
        lx = int(round(wx)) - self.origin_x
        ly = int(round(wy)) - self.origin_y
        if lx < 0 or ly < 0 or lx >= self.width or ly >= self.height_px:
            return None
        return lx, ly

    def sample(self, wx: float, wy: float) -> Optional[float]:
        """Height in 0..1, or None if outside the chunk or in the void."""
        loc = self._local(wx, wy)
        if loc is None:
            return None
        lx, ly = loc
        if self._void[ly, lx]:
            return None
        return float(self._height[ly, lx]) / 255.0

    def sample_u8(self, wx: float, wy: float) -> Optional[int]:
        loc = self._local(wx, wy)
        if loc is None:
            return None
        lx, ly = loc
        if self._void[ly, lx]:
            return None
        return int(self._height[ly, lx])

    def gradient(self, wx: float, wy: float, step: Optional[int] = None) -> Optional[tuple[float, float]]:
        """(dh/dx, dh/dy) in height-units per pixel.

        Neighbours that fall in void use the opposite step; still-void returns None.
        """
        h0 = self.sample(wx, wy)
        if h0 is None:
            return None
        use = max(1, int(self.gradient_step if step is None else step))

        def _axis(dx: float, dy: float) -> Optional[float]:
            hp = self.sample(wx + dx, wy + dy)
            if hp is not None:
                return (hp - h0) / use
            hn = self.sample(wx - dx, wy - dy)
            if hn is not None:
                return (h0 - hn) / use
            return None

        gx = _axis(float(use), 0.0)
        gy = _axis(0.0, float(use))
        if gx is None or gy is None:
            return None
        return (gx, gy)

    def slope_along(self, wx: float, wy: float, dir_x: float, dir_y: float) -> Optional[float]:
        g = self.gradient(wx, wy)
        if g is None:
            return None
        length = (dir_x * dir_x + dir_y * dir_y) ** 0.5
        if length < 1e-6:
            return 0.0
        return (g[0] * dir_x + g[1] * dir_y) / length

    def debug_overlay_rgba(self, alpha: int = HEIGHT_OVERLAY_ALPHA) -> np.ndarray:
        """Land pixels: red = high, blue = low. Void is transparent."""
        a = int(max(0, min(255, alpha)))
        rgba = np.zeros((self.height_px, self.width, 4), dtype=np.uint8)
        land = ~self._void
        h8 = self._height
        rgba[land, 0] = h8[land]
        rgba[land, 2] = 255 - h8[land]
        rgba[land, 3] = a
        return rgba


def world_scale_for_layout(layout_manager) -> float:
    tmx = getattr(layout_manager, "tmxdata", None)
    tilewidth = getattr(tmx, "tilewidth", None) if tmx is not None else None
    if not tilewidth:
        raise ValueError("layout has no tmx tilewidth; cannot assert world scale")
    return float(TILESIZE) / float(tilewidth)


def grade_acceleration(
    gradient: Optional[tuple[float, float]],
    *,
    g: float = TERRAIN_G,
    deadzone: float = GRADE_DEADZONE,
) -> tuple[float, float]:
    """Downhill accel (px/frame²). Opposite the height gradient. Flat is (0, 0)."""
    if gradient is None:
        return (0.0, 0.0)
    gx = float(gradient[0])
    gy = float(gradient[1])
    mag = (gx * gx + gy * gy) ** 0.5
    if mag <= deadzone:
        return (0.0, 0.0)
    return (-g * gx, -g * gy)


def _resolve_layout_dir(layout_dir: str | Path) -> Path:
    layout = Path(layout_dir)
    if not layout.is_absolute():
        layout = (Path(__file__).resolve().parent / layout).resolve()
    else:
        layout = layout.resolve()
    return layout


def load_chunk_00_01(layout_dir: str | Path, *, world_scale: float = 1.0) -> ChunkHeightmap:
    layout = _resolve_layout_dir(layout_dir)
    height_path = layout / CHUNK_00_01_RELATIVE[0]
    source_path = layout / CHUNK_00_01_RELATIVE[1]
    return ChunkHeightmap(
        height_path,
        source_path,
        CHUNK_00_01_WORLD_RECT,
        world_scale=world_scale,
    )


def try_load_chunk_00_01(
    layout_dir: str | Path, *, world_scale: float = 1.0
) -> Optional[ChunkHeightmap]:
    if abs(float(world_scale) - 1.0) > 1e-6:
        return None
    layout = _resolve_layout_dir(layout_dir)
    height_path = layout / CHUNK_00_01_RELATIVE[0]
    source_path = layout / CHUNK_00_01_RELATIVE[1]
    if not height_path.is_file() or not source_path.is_file():
        return None
    try:
        return load_chunk_00_01(layout, world_scale=world_scale)
    except (OSError, ValueError):
        return None
