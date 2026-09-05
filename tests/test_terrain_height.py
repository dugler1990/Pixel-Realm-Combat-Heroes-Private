"""Chunk_00_01 heightmap: void vs zero, goldens, scale, gradient step."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Code"))

from terrain_height import (  # noqa: E402
    CHUNK_00_01_WORLD_RECT,
    GOLDEN_HEIGHT_U8,
    GOLDEN_RIDGE,
    GOLDEN_SHELF,
    GOLDEN_VOID,
    GOLDEN_WASH,
    GRADIENT_STEP_PX,
    HEIGHT_U8_TOLERANCE,
    PHYSICS_GRADIENT_STEP,
    VOID_ALPHA_MAX,
    VOID_RGB_MAX,
    ChunkHeightmap,
    grade_acceleration,
    load_chunk_00_01,
    try_load_chunk_00_01,
)
from tools.painted_map_pipeline.heightmap.align import (  # noqa: E402
    VOID_ALPHA_MAX as TOOLS_VOID_ALPHA_MAX,
)
from tools.painted_map_pipeline.heightmap.align import (
    VOID_RGB_MAX as TOOLS_VOID_RGB_MAX,
)

LAYOUT = (
    Path(__file__).resolve().parents[1]
    / "levels"
    / "Frostreach"
    / "sunspine_7x6_play"
)


@pytest.fixture(scope="module")
def heightmap():
    return load_chunk_00_01(LAYOUT, world_scale=1.0)


def test_gradient_step_is_paint_scale_not_one_pixel():
    assert 8 <= GRADIENT_STEP_PX <= 16


def test_scale_not_one_is_rejected():
    with pytest.raises(ValueError, match="scale="):
        ChunkHeightmap(
            LAYOUT / "export/sam3_chunks/chunk_00_01/heightmap.png",
            LAYOUT / "export/sam3_chunks/chunk_00_01/source.png",
            CHUNK_00_01_WORLD_RECT,
            world_scale=1.1,
        )


def test_golden_ridge_and_wash(heightmap):
    ridge = heightmap.sample_u8(*GOLDEN_RIDGE)
    wash = heightmap.sample_u8(*GOLDEN_WASH)
    assert ridge is not None
    assert wash is not None
    assert abs(ridge - GOLDEN_HEIGHT_U8[GOLDEN_RIDGE]) <= HEIGHT_U8_TOLERANCE
    assert abs(wash - GOLDEN_HEIGHT_U8[GOLDEN_WASH]) <= HEIGHT_U8_TOLERANCE


def test_void_is_none_not_zero(heightmap):
    assert heightmap.sample(*GOLDEN_VOID) is None
    assert heightmap.sample_u8(*GOLDEN_VOID) is None


def test_legal_low_ground_zero_is_zero(heightmap):
    land_and_zero = (~heightmap._void) & (heightmap._height == 0)
    coords = land_and_zero.nonzero()
    assert coords[0].size > 0
    ly = int(coords[0][0])
    lx = int(coords[1][0])
    wx = heightmap.origin_x + lx
    wy = heightmap.origin_y + ly
    assert heightmap.sample(wx, wy) == 0.0
    assert heightmap.sample_u8(wx, wy) == 0


def test_off_chunk_is_none(heightmap):
    ox, oy, rw, rh = CHUNK_00_01_WORLD_RECT
    assert heightmap.sample(ox - 1, oy) is None
    assert heightmap.sample(ox, oy - 1) is None
    assert heightmap.sample(ox + rw, oy) is None
    assert heightmap.sample(ox, oy + rh) is None


def test_gradient_at_ridge_uses_stated_step(heightmap):
    assert heightmap.gradient_step == GRADIENT_STEP_PX
    g = heightmap.gradient(*GOLDEN_RIDGE)
    assert g is not None
    assert len(g) == 2


def test_grade_is_downhill_and_ridge_is_steeper_than_shelf(heightmap):
    assert grade_acceleration(None) == (0.0, 0.0)
    assert grade_acceleration((0.0, 0.0)) == (0.0, 0.0)
    ridge = heightmap.gradient(*GOLDEN_RIDGE, step=PHYSICS_GRADIENT_STEP)
    shelf = heightmap.gradient(*GOLDEN_SHELF, step=PHYSICS_GRADIENT_STEP)
    assert ridge is not None
    ax, ay = grade_acceleration(ridge)
    assert ax * ridge[0] + ay * ridge[1] < 0
    ridge_mag = (ax * ax + ay * ay) ** 0.5
    if shelf is None:
        shelf_mag = 0.0
    else:
        sx, sy = grade_acceleration(shelf)
        shelf_mag = (sx * sx + sy * sy) ** 0.5
    assert ridge_mag > 0.0
    assert ridge_mag > shelf_mag


def test_debug_overlay_is_red_high_blue_low(heightmap):
    rgba = heightmap.debug_overlay_rgba(alpha=210)
    lx = GOLDEN_RIDGE[0] - heightmap.origin_x
    ly = GOLDEN_RIDGE[1] - heightmap.origin_y
    wx = GOLDEN_WASH[0] - heightmap.origin_x
    wy = GOLDEN_WASH[1] - heightmap.origin_y
    vx = GOLDEN_VOID[0] - heightmap.origin_x
    vy = GOLDEN_VOID[1] - heightmap.origin_y
    ridge = rgba[ly, lx]
    wash = rgba[wy, wx]
    void = rgba[vy, vx]
    assert ridge[0] > wash[0]
    assert ridge[2] < wash[2]
    assert ridge[3] == 210
    assert void[3] == 0


def test_void_constants_match_tools_align():
    assert VOID_RGB_MAX == TOOLS_VOID_RGB_MAX
    assert VOID_ALPHA_MAX == TOOLS_VOID_ALPHA_MAX


def test_try_load_skips_bad_scale_and_missing():
    assert try_load_chunk_00_01(LAYOUT, world_scale=1.1) is None
    assert try_load_chunk_00_01("/no/such/layout", world_scale=1.0) is None
    loaded = try_load_chunk_00_01(LAYOUT, world_scale=1.0)
    assert loaded is not None
    assert loaded.sample_u8(*GOLDEN_RIDGE) is not None
