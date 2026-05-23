import heapq
import math

import pygame

from .walk_grid import WalkGrid

_MAX_SEARCH_NODES = 8000
_MAX_PATH_WAYPOINTS = 256

_NEIGHBORS = (
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, math.sqrt(2)),
    (1, -1, math.sqrt(2)),
    (-1, 1, math.sqrt(2)),
    (-1, -1, math.sqrt(2)),
)


def find_path(grid, start_px, end_px):
    """Return world-space waypoints from start_px to end_px, or [] if unreachable."""
    if grid is None or grid.cols == 0 or grid.rows == 0:
        return []

    start_col, start_row = grid.world_to_cell(start_px[0], start_px[1])
    end_col, end_row = grid.world_to_cell(end_px[0], end_px[1])

    start = grid.nearest_walkable(start_col, start_row)
    end = grid.nearest_walkable(end_col, end_row)
    if start is None or end is None:
        return []
    if start == end:
        return [grid.cell_center(end[0], end[1])]

    path_cells = _astar(grid, start[0], start[1], end[0], end[1])
    if not path_cells:
        return []

    waypoints = [grid.cell_center(col, row) for col, row in path_cells]
    if len(waypoints) > _MAX_PATH_WAYPOINTS:
        stride = max(1, len(waypoints) // _MAX_PATH_WAYPOINTS)
        waypoints = waypoints[::stride]
        if waypoints[-1] != grid.cell_center(end[0], end[1]):
            waypoints.append(grid.cell_center(end[0], end[1]))
    return waypoints


def _astar(grid, start_col, start_row, end_col, end_row):
    start = (start_col, start_row)
    goal = (end_col, end_row)
    open_heap = []
    heapq.heappush(open_heap, (0.0, start))
    came_from = {}
    g_score = {start: 0.0}
    nodes_expanded = 0

    while open_heap and nodes_expanded < _MAX_SEARCH_NODES:
        _, current = heapq.heappop(open_heap)
        nodes_expanded += 1
        if current == goal:
            return _reconstruct_path(came_from, current)

        for dc, dr, step_cost in _NEIGHBORS:
            ncol = current[0] + dc
            nrow = current[1] + dr
            if not grid.is_walkable(ncol, nrow):
                continue
            if dc != 0 and dr != 0:
                if not grid.is_walkable(current[0] + dc, current[1]) or not grid.is_walkable(
                    current[0], current[1] + dr
                ):
                    continue
            neighbor = (ncol, nrow)
            tentative = g_score[current] + step_cost
            if tentative >= g_score.get(neighbor, float("inf")):
                continue
            came_from[neighbor] = current
            g_score[neighbor] = tentative
            f_score = tentative + _heuristic(neighbor, goal)
            heapq.heappush(open_heap, (f_score, neighbor))

    return []


def _heuristic(cell, goal):
    dx = abs(cell[0] - goal[0])
    dy = abs(cell[1] - goal[1])
    return math.hypot(dx, dy)


def _reconstruct_path(came_from, current):
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path
