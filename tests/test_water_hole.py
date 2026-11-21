"""The hole keeps the water inside it. No window."""

import sys
from pathlib import Path

import numpy as np

CODE_DIR = Path(__file__).resolve().parents[1] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from combat_validation_driver import (  # noqa: E402
    apply_scene_conditions,
    clear_scene_conditions,
)
from water_hole import compose, layout_for  # noqa: E402


def _boundary(ellipse, samples=96):
    return [ellipse.point_at(i / samples) for i in range(samples)]


def test_scene_conditions_pin_the_hour_and_clear_the_grass():
    class _Weather:
        pinned_hour = None
        current_time = 3.0

    class _Grass:
        def __init__(self):
            self.grass_tiles = {"a": 1}

    class _Bench:
        grass_benchmark_enabled = True

    class _Layout:
        def __init__(self):
            self.daytime_layout = False
            self.lighting = object()
            self.grass_manager = _Grass()

    class _Level:
        def __init__(self):
            self.weather = _Weather()
            self.layout_manager = _Layout()
            self.benchmark_runtime = _Bench()

    class _Scene:
        HOUR = 14
        GRASS = False

    level = _Level()
    saved = apply_scene_conditions(level, _Scene())
    assert level.weather.pinned_hour == 14
    assert level.weather.current_time == 14.0
    assert level.layout_manager.daytime_layout is True
    assert level.layout_manager.grass_manager.grass_tiles == {}
    assert level.benchmark_runtime.grass_benchmark_enabled is False
    clear_scene_conditions(level, saved)
    assert level.weather.pinned_hour is None
    assert level.layout_manager.daytime_layout is False


def test_flat_cut_is_a_circle_filled_by_water():
    layout = layout_for("flat", 960, 600)
    assert layout.opening.rx == layout.opening.ry
    assert layout.water == layout.opening
    assert layout.far_wall == 0
    assert layout.near_wall == 0


def test_pit_far_wall_is_taller_than_the_near_wall():
    layout = layout_for("pit", 960, 600)
    assert layout.opening.ry < layout.opening.rx
    assert layout.far_wall > layout.near_wall > 0
    for x, y in _boundary(layout.water):
        assert layout.opening.contains(x, y)


def test_cliff_face_is_the_drop_above_the_water():
    beach = layout_for("pit", 960, 600)
    cliff = layout_for("cliff", 960, 600)
    assert cliff.opening == beach.opening
    assert cliff.waterline is not None
    assert cliff.far_wall > beach.far_wall * 2
    assert cliff.far_wall > cliff.near_wall > 0
    width, height = 320, 200
    drawn = layout_for("cliff", width, height)
    _ground, water, wall = compose(drawn, width, height)
    x = int(drawn.opening.cx)
    assert wall[int(drawn.opening.cy), x, 3] == 255
    assert water[int(drawn.opening.cy), x, 3] == 0
    foot = int((drawn.waterline + drawn.opening.cy + drawn.opening.ry) / 2)
    assert water[foot, x, 3] == 255
    assert wall[foot, x, 3] == 0


def test_cube_is_an_isometric_box_with_the_pool_on_the_floor():
    layout = layout_for("cube", 320, 200)
    cut = layout.cube
    north = cut.floor[0][1] - cut.rim[0][1]
    south = cut.rim[2][1] - cut.floor[2][1]
    assert north > south > 0
    assert layout_for("cliff", 320, 200).cube is None
    ground, water, wall = compose(layout, 320, 200)
    cliff_y = int((cut.rim[0][1] + cut.floor[0][1]) / 2)
    assert wall[cliff_y, int(cut.cx), 3] == 255
    assert water[cliff_y, int(cut.cx), 3] == 0
    pool_x = int(sum(p[0] for p in cut.floor) / 4)
    pool_y = int(sum(p[1] for p in cut.floor) / 4)
    assert water[pool_y, pool_x, 3] == 255
    assert wall[pool_y, pool_x, 3] == 0
    outside = (int(cut.rim[3][0]) + 2, int(cut.rim[0][1]) + 2)
    assert ground[outside[1], outside[0], 3] == 255
    assert water[outside[1], outside[0], 3] == 0


def test_shaft_walls_drop_straight_down():
    shaft = layout_for("shaft", 320, 200)
    cube = layout_for("cube", 320, 200)
    drop = shaft.cube.floor[0][1] - shaft.cube.rim[0][1]
    for rim_pt, floor_pt in zip(shaft.cube.rim, shaft.cube.floor):
        assert abs(floor_pt[0] - rim_pt[0]) < 1e-6
        assert abs((floor_pt[1] - rim_pt[1]) - drop) < 1e-6
    assert drop > 10
    assert cube.cube.floor[1][0] < cube.cube.rim[1][0] - 10
    ground, water, wall = compose(shaft, 320, 200)
    edge_x = int(shaft.cube.rim[1][0]) - 3
    edge_y = int((shaft.cube.rim[1][1] + shaft.cube.floor[1][1]) / 2)
    assert wall[edge_y, edge_x, 3] == 255
    pool_y = int(shaft.cube.cy + drop)
    assert water[pool_y, int(shaft.cube.cx), 3] == 255
    assert ground[int(shaft.cube.rim[0][1]) - 3, int(shaft.cube.cx), 3] == 255


def test_water_pixels_stay_inside_the_opening():
    for style in ("flat", "pit", "cliff"):
        layout = layout_for(style, 320, 200)
        ground, water, wall = compose(layout, 320, 200)
        water_px = water[..., 3] > 0
        assert water_px[int(layout.water.cy), int(layout.water.cx)]
        yy, xx = np.ogrid[:200, :320]
        outside = ((xx - layout.opening.cx) / layout.opening.rx) ** 2 + (
            (yy - layout.opening.cy) / layout.opening.ry
        ) ** 2 > 1.0
        assert not np.any(water_px & outside)
        assert not np.any((ground[..., 3] > 0) & ~outside)
        if style == "pit":
            far_y = int((layout.opening.cy - layout.opening.ry + layout.water.cy - layout.water.ry) / 2)
            assert wall[far_y, int(layout.opening.cx), 3] == 255
            assert wall[int(layout.water.cy), int(layout.water.cx), 3] == 0
