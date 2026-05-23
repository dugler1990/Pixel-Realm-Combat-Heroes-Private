import math

import pygame

from hashRect import HashableRect

_DEFAULT_PROBE_SIZE = 24


class WalkGrid:
    """Tile walkability grid for macro pathfinding."""

    def __init__(self, blocked, cell_size, world_width, world_height):
        self.blocked = blocked
        self.cell_size = int(cell_size)
        self.world_width = int(world_width)
        self.world_height = int(world_height)
        self.rows = len(blocked)
        self.cols = len(blocked[0]) if self.rows else 0

    def in_bounds(self, col, row):
        return 0 <= col < self.cols and 0 <= row < self.rows

    def is_walkable(self, col, row):
        if not self.in_bounds(col, row):
            return False
        return not self.blocked[row][col]

    def world_to_cell(self, x, y):
        col = int(x // self.cell_size)
        row = int(y // self.cell_size)
        return col, row

    def cell_center(self, col, row):
        cx = col * self.cell_size + self.cell_size // 2
        cy = row * self.cell_size + self.cell_size // 2
        return pygame.math.Vector2(cx, cy)

    def nearest_walkable(self, col, row, max_radius=12):
        if self.is_walkable(col, row):
            return col, row
        for radius in range(1, max_radius + 1):
            for dc in range(-radius, radius + 1):
                for dr in range(-radius, radius + 1):
                    if abs(dc) != radius and abs(dr) != radius:
                        continue
                    nc, nr = col + dc, row + dr
                    if self.is_walkable(nc, nr):
                        return nc, nr
        return None


def build_walk_grid(
    obstacle_quad_tree,
    world_width,
    world_height,
    cell_size,
    probe_size=_DEFAULT_PROBE_SIZE,
):
    """Rasterize static obstacles into a blocked grid using the obstacle quad tree."""
    cell_size = int(cell_size)
    cols = max(1, int(math.ceil(world_width / cell_size)))
    rows = max(1, int(math.ceil(world_height / cell_size)))
    blocked = [[False] * cols for _ in range(rows)]
    half = max(1, probe_size // 2)

    if obstacle_quad_tree is None:
        return WalkGrid(blocked, cell_size, world_width, world_height)

    for row in range(rows):
        for col in range(cols):
            center = (
                col * cell_size + cell_size // 2,
                row * cell_size + cell_size // 2,
            )
            probe = pygame.Rect(
                center[0] - half,
                center[1] - half,
                probe_size,
                probe_size,
            )
            hits = obstacle_quad_tree.hit(HashableRect(probe))
            if not hits:
                continue
            if _probe_blocked(probe, hits):
                blocked[row][col] = True

    return WalkGrid(blocked, cell_size, world_width, world_height)


def _probe_blocked(probe_rect, hits):
    for item in hits:
        obstacle_rect = getattr(item, "rect", None)
        if obstacle_rect is None:
            continue
        if not probe_rect.colliderect(obstacle_rect):
            continue
        mask = getattr(item, "mask", None)
        if mask is None:
            return True
        dx = obstacle_rect.x - probe_rect.x
        dy = obstacle_rect.y - probe_rect.y
        probe_mask = pygame.mask.Mask((probe_rect.width, probe_rect.height), fill=True)
        if probe_mask.overlap_area(mask, (dx, dy)) > 0:
            return True
    return False
