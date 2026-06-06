import math

import pygame

from hashRect import HashableRect

_NEAREST_WALKABLE_WORLD_RADIUS = 240


class WalkGrid:
    """Tile walkability grid for macro pathfinding."""

    def __init__(self, blocked, cell_w, cell_h, world_width, world_height):
        self.blocked = blocked
        self.cell_w = int(cell_w)
        self.cell_h = int(cell_h)
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
        col = int(x // self.cell_w)
        row = int(y // self.cell_h)
        return col, row

    def cell_rect(self, col, row):
        return pygame.Rect(
            col * self.cell_w,
            row * self.cell_h,
            self.cell_w,
            self.cell_h,
        )

    def cell_center(self, col, row):
        rect = self.cell_rect(col, row)
        return pygame.math.Vector2(rect.centerx, rect.centery)

    def nearest_walkable(self, col, row, max_radius=None):
        step = max(1, self.cell_w, self.cell_h)
        if max_radius is None:
            max_radius = max(8, _NEAREST_WALKABLE_WORLD_RADIUS // step)
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
    cell_w,
    cell_h,
    probe_w=None,
    probe_h=None,
):
    """Rasterize static obstacles into a blocked grid using the obstacle quad tree."""
    cell_w = int(cell_w)
    cell_h = int(cell_h)
    probe_w = int(probe_w if probe_w is not None else cell_w)
    probe_h = int(probe_h if probe_h is not None else cell_h)
    cols = max(1, int(math.ceil(world_width / cell_w)))
    rows = max(1, int(math.ceil(world_height / cell_h)))
    blocked = [[False] * cols for _ in range(rows)]

    if obstacle_quad_tree is None:
        return WalkGrid(blocked, cell_w, cell_h, world_width, world_height)

    for row in range(rows):
        for col in range(cols):
            probe = pygame.Rect(
                col * cell_w,
                row * cell_h,
                probe_w,
                probe_h,
            )
            hits = obstacle_quad_tree.hit(HashableRect(probe))
            if not hits:
                continue
            if _probe_blocked(probe, hits):
                blocked[row][col] = True

    return WalkGrid(blocked, cell_w, cell_h, world_width, world_height)


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


def block_walk_grid_cells_for_item(grid, item, cell_w, cell_h, probe_w, probe_h):
    """Mark walkable cells blocked by a newly added static obstacle (add-only)."""
    obstacle_rect = getattr(item, "rect", None)
    if obstacle_rect is None or grid.cols == 0 or grid.rows == 0:
        return

    cell_w = int(cell_w)
    cell_h = int(cell_h)
    probe_w = int(probe_w)
    probe_h = int(probe_h)
    pad_x = max(0, probe_w - cell_w)
    pad_y = max(0, probe_h - cell_h)
    min_col = max(0, int((obstacle_rect.left - pad_x) // cell_w))
    min_row = max(0, int((obstacle_rect.top - pad_y) // cell_h))
    max_col = min(grid.cols - 1, int((obstacle_rect.right + pad_x) // cell_w))
    max_row = min(grid.rows - 1, int((obstacle_rect.bottom + pad_y) // cell_h))

    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            if grid.blocked[row][col]:
                continue
            probe = pygame.Rect(
                col * cell_w,
                row * cell_h,
                probe_w,
                probe_h,
            )
            if _probe_blocked(probe, [item]):
                grid.blocked[row][col] = True
