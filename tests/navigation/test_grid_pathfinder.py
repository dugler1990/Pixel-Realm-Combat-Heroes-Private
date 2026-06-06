import pygame

from navigation.grid_pathfinder import find_path
from navigation.walk_grid import WalkGrid


def _grid_with_vertical_wall(cols, rows, wall_col, gap_row=None, cell_size=50):
    blocked = [[False] * cols for _ in range(rows)]
    for row in range(rows):
        if gap_row is not None and row == gap_row:
            continue
        blocked[row][wall_col] = True
    return WalkGrid(blocked, cell_size, cell_size, cols * cell_size, rows * cell_size)


def test_path_goes_around_wall():
    grid = _grid_with_vertical_wall(10, 6, wall_col=5, gap_row=0)
    start = (25, 150)
    end = (425, 150)
    path = find_path(grid, start, end)
    assert len(path) >= 2
    for waypoint in path:
        col, row = grid.world_to_cell(waypoint.x, waypoint.y)
        assert not grid.blocked[row][col]


def test_path_empty_when_fully_walled_goal():
    grid = _grid_with_vertical_wall(6, 6, wall_col=3)
    for row in range(6):
        grid.blocked[row][5] = True
    path = find_path(grid, (25, 25), (275, 275))
    assert path == []


def test_nearest_walkable_for_blocked_start():
    grid = WalkGrid([[True, False], [False, False]], 50, 50, 100, 100)
    path = find_path(grid, (25, 25), (75, 75))
    assert len(path) >= 1
