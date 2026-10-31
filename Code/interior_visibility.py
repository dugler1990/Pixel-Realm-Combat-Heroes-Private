"""What you can see inside a building: the floor you have explored, and its walls.

Inside, a building is black but for its floor and walls (see Building), and those are black
too until your feet have been near them. Near is measured along the floor, a cell at a time,
so exploring never shows a room through a wall -- only through the doorway, as far as you
could walk. The walls joined to that floor, within the same reach, show with it. Explored
stays explored.

The fog is one small surface, a pixel per cell: opaque over unexplored floor and walls and a
cell round them, clear everywhere else. The camera stretches it over the building, which
softens its edges -- the ring keeps that softening off the edge of what is unexplored, and
clear stone and sand mean the fog darkens nothing else. Exploring re-uploads a few KB.
"""

import numpy as np
import pygame

from Settings import INTERIOR_EXPLORE_RADIUS

# Floor px per fog cell.
CELL = 16


def floor_cells(rect, mask, cell=CELL):
    """(rows, cols) bool over `rect`: True where any of the cell's pixels is floor.

    Any, not the centre: a cell on a room's edge that is mostly stone still holds floor,
    and fogging that cell is what keeps the edge of an unexplored room dark.
    """
    cols = max(1, -(-rect.width // cell))
    rows = max(1, -(-rect.height // cell))
    if mask is None:
        return np.ones((rows, cols), dtype=bool)
    width, height = mask.get_size()
    width, height = min(width, cols * cell), min(height, rows * cell)
    shape = mask.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
    floor = np.zeros((rows * cell, cols * cell), dtype=bool)
    floor[:height, :width] = pygame.surfarray.array_alpha(shape).T[:height, :width] > 0
    return floor.reshape(rows, cell, cols, cell).any(axis=(1, 3))


def _grow(cells):
    """`cells` and every cell touching one, in all eight directions."""
    grown = cells.copy()
    grown[1:, :] |= cells[:-1, :]
    grown[:-1, :] |= cells[1:, :]
    grown[:, 1:] |= cells[:, :-1]
    grown[:, :-1] |= cells[:, 1:]
    grown[1:, 1:] |= cells[:-1, :-1]
    grown[1:, :-1] |= cells[:-1, 1:]
    grown[:-1, 1:] |= cells[1:, :-1]
    grown[:-1, :-1] |= cells[1:, 1:]
    return grown


class InteriorFog:
    """One building's floor and walls, and how much of them you have explored.

    `mask` is the floor and `walls` the walls (or None), both `rect`-sized.
    """

    def __init__(self, rect, mask, walls=None, cell=CELL, radius=INTERIOR_EXPLORE_RADIUS):
        self.cell = int(cell)
        self.floor = floor_cells(rect, mask, self.cell)
        # Shown once explored, but never walked through while exploring.
        self.walls = (floor_cells(rect, walls, self.cell) & ~self.floor if walls is not None
                      else np.zeros_like(self.floor))
        rows, cols = self.floor.shape
        # The chamber's rect, rounded up to whole cells: where the camera stretches the fog.
        self.rect = pygame.Rect(rect.x, rect.y, cols * self.cell, rows * self.cell)
        self.reach = max(1, int(round(radius / self.cell)))
        self.explored = np.zeros_like(self.floor)
        self.surface = pygame.Surface((cols, rows), pygame.SRCALPHA)
        self.surface.fill((0, 0, 0, 0))
        self._paint()
        # Set when the surface changes so the camera uploads it again; the camera clears it.
        self.changed = False
        self._from = None

    def _paint(self):
        """Opaque over unexplored floor and walls and the ring of cells round them; clear
        elsewhere."""
        cover = _grow((self.floor | self.walls) & ~self.explored) & ~self.explored
        alpha = pygame.surfarray.pixels_alpha(self.surface)
        alpha[:] = np.where(cover.T, 255, 0)
        del alpha

    def _cell(self, point):
        row = int((point[1] - self.rect.y) // self.cell)
        col = int((point[0] - self.rect.x) // self.cell)
        rows, cols = self.floor.shape
        if 0 <= row < rows and 0 <= col < cols:
            return row, col
        return None

    def explore_from(self, point):
        """Mark the floor within reach of `point`, walking, and the walls joined to it, as
        explored."""
        here = self._cell(point)
        if here is None or here == self._from:
            return
        self._from = here
        row, col = here
        if not self.floor[row, col]:
            return
        reach = self.reach
        top, left = max(0, row - reach), max(0, col - reach)
        window = (slice(top, row + reach + 1), slice(left, col + reach + 1))
        floor = self.floor[window]
        # Round, not square: eight-way steps reach the window's corners as soon as its sides.
        dy, dx = np.ogrid[top - row:top - row + floor.shape[0], left - col:left - col + floor.shape[1]]
        near = dy * dy + dx * dx <= reach * reach
        reached = np.zeros_like(floor)
        reached[row - top, col - left] = True
        for walkable in (floor & near, self.walls[window] & near):
            # First along the floor; then out from it into the walls, which add no floor.
            for _ in range(reach):
                grown = reached | (_grow(reached) & walkable)
                if np.array_equal(grown, reached):
                    break
                reached = grown
        if not (reached & ~self.explored[window]).any():
            return
        self.explored[window] |= reached
        self._paint()
        self.changed = True

    def explored_at(self, point):
        """Has the floor under `point` been explored?"""
        here = self._cell(point)
        return here is not None and bool(self.explored[here])
