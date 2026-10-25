"""What you can see inside a building.

The chamber the pipeline traced is the walkable floor. From above it is one painting,
so without a rule you see every room the moment the roof opens. This module is that
rule, the same one the 2000s dungeon games used: walls block, unseen floor is black.

How it is defined, on purpose, in one place:

  1. Rasterize the chamber mask onto a coarse grid. A cell whose centre is floor
     is walkable and lets light through. Everything else is a wall.
  2. From the subject's feet, mark every walkable cell that has a clear line to
     them and sits inside a vision radius.
  3. Those cells stay the painted interior. The rest of the floor is black.

A corridor then shows as that corridor (and a sliver through a doorway). A room
shows as that room. Around a corner stays dark. No new TMX is required: the
chamber already is the floor, and the walls are whatever is not the floor.

Room polygons (`room_of`) stay spawn areas. They are the eroded cores of rooms,
too small to be visibility regions. Whole-room reveal on top of line-of-sight
can use better polygons later; the hook is "the cell you stand in", not those
cores.

The fog surface is chamber-sized and rebuilt when the subject steps into a new
grid cell. The camera invalidates the GPU cache on that change so the upload
is once per step, not once per frame.
"""

from Settings import INTERIOR_SIGHT_CELL, INTERIOR_SIGHT_RADIUS

import pygame


FOG_RGBA = (0, 0, 0, 255)


def _supercover(x0, y0, x1, y1):
    """Every grid cell the segment from (x0, y0) to (x1, y1) crosses."""
    dx = x1 - x0
    dy = y1 - y0
    nx = abs(dx)
    ny = abs(dy)
    sign_x = 0 if dx == 0 else (1 if dx > 0 else -1)
    sign_y = 0 if dy == 0 else (1 if dy > 0 else -1)
    x, y = x0, y0
    yield x, y
    ix = iy = 0
    while ix < nx or iy < ny:
        decision = (1 + 2 * ix) * ny - (1 + 2 * iy) * nx
        if decision == 0:
            x += sign_x
            y += sign_y
            ix += 1
            iy += 1
            yield x, y
        elif decision < 0:
            x += sign_x
            ix += 1
            yield x, y
        else:
            y += sign_y
            iy += 1
            yield x, y


def has_line_of_sight(walkable, x0, y0, x1, y1):
    """Can (x0, y0) see walkable cell (x1, y1) without crossing a wall?

    The destination must be floor. Intermediate cells must be floor. A diagonal
    step that slips between two blocked orthogonals is treated as blocked --
    that is the corner you cannot see around.
    """
    rows = len(walkable)
    cols = len(walkable[0]) if rows else 0
    if not (0 <= x0 < cols and 0 <= y0 < rows and walkable[y0][x0]):
        return False
    if not (0 <= x1 < cols and 0 <= y1 < rows and walkable[y1][x1]):
        return False
    prev = (x0, y0)
    for x, y in _supercover(x0, y0, x1, y1):
        if (x, y) == (x0, y0):
            continue
        if not (0 <= x < cols and 0 <= y < rows):
            return False
        if (x, y) == (x1, y1):
            dx = x - prev[0]
            dy = y - prev[1]
            if dx and dy:
                side_x = walkable[prev[1]][prev[0] + dx]
                side_y = walkable[prev[1] + dy][prev[0]]
                if not side_x and not side_y:
                    return False
            return True
        if not walkable[y][x]:
            return False
        dx = x - prev[0]
        dy = y - prev[1]
        if dx and dy:
            side_x = 0 <= prev[0] + dx < cols and walkable[prev[1]][prev[0] + dx]
            side_y = 0 <= prev[1] + dy < rows and walkable[prev[1] + dy][prev[0]]
            if not side_x and not side_y:
                return False
        prev = (x, y)
    return True


def visible_cells(walkable, origin, radius_cells):
    """Set of (col, row) walkable cells visible from `origin` within `radius_cells`."""
    ox, oy = origin
    rows = len(walkable)
    cols = len(walkable[0]) if rows else 0
    found = set()
    if not (0 <= ox < cols and 0 <= oy < rows and walkable[oy][ox]):
        return found
    r2 = radius_cells * radius_cells
    y0 = max(0, oy - radius_cells)
    y1 = min(rows, oy + radius_cells + 1)
    x0 = max(0, ox - radius_cells)
    x1 = min(cols, ox + radius_cells + 1)
    for row in range(y0, y1):
        for col in range(x0, x1):
            if (col - ox) * (col - ox) + (row - oy) * (row - oy) > r2:
                continue
            if has_line_of_sight(walkable, ox, oy, col, row):
                found.add((col, row))
    return found


def rasterize_chamber(chamber_rect, chamber_mask, cell):
    """Walkable grid covering `chamber_rect`. True where the cell centre is floor."""
    cols = max(1, (chamber_rect.width + cell - 1) // cell)
    rows = max(1, (chamber_rect.height + cell - 1) // cell)
    walkable = [[False] * cols for _ in range(rows)]
    mask_w, mask_h = (chamber_mask.get_size() if chamber_mask is not None else (0, 0))
    for row in range(rows):
        for col in range(cols):
            wx = chamber_rect.x + col * cell + cell // 2
            wy = chamber_rect.y + row * cell + cell // 2
            if not chamber_rect.collidepoint(wx, wy):
                continue
            if chamber_mask is None:
                walkable[row][col] = True
                continue
            lx = int(wx) - chamber_rect.x
            ly = int(wy) - chamber_rect.y
            if 0 <= lx < mask_w and 0 <= ly < mask_h and chamber_mask.get_at((lx, ly)):
                walkable[row][col] = True
    return walkable


class InteriorSight:
    """Per-building line-of-sight fog. See the module docstring for the rule."""

    def __init__(self, chamber_rect, chamber_mask, cell=INTERIOR_SIGHT_CELL,
                 radius=INTERIOR_SIGHT_RADIUS):
        self.cell = int(cell)
        self.radius = float(radius)
        self.chamber_rect = chamber_rect
        self.walkable = rasterize_chamber(chamber_rect, chamber_mask, self.cell)
        self.rows = len(self.walkable)
        self.cols = len(self.walkable[0]) if self.rows else 0
        self.fog_rect = pygame.Rect(
            chamber_rect.x, chamber_rect.y,
            self.cols * self.cell, self.rows * self.cell,
        )
        self.fog = pygame.Surface(self.fog_rect.size, pygame.SRCALPHA)
        self.visible = set()
        self._origin_cell = None
        self.dirty = False
        self._paint_unseen(set())

    @classmethod
    def from_chamber(cls, chamber_rect, chamber_mask, cell=INTERIOR_SIGHT_CELL,
                     radius=INTERIOR_SIGHT_RADIUS):
        return cls(chamber_rect, chamber_mask, cell=cell, radius=radius)

    @property
    def active(self):
        """True when some walkable floor is currently blacked out."""
        return bool(self.visible) and self._unseen_count() > 0

    def world_to_cell(self, point):
        col = int((point[0] - self.chamber_rect.x) // self.cell)
        row = int((point[1] - self.chamber_rect.y) // self.cell)
        return col, row

    def cell_center(self, col, row):
        return (
            self.chamber_rect.x + col * self.cell + self.cell // 2,
            self.chamber_rect.y + row * self.cell + self.cell // 2,
        )

    def sees(self, point):
        col, row = self.world_to_cell(point)
        return (col, row) in self.visible

    def hide(self):
        """Leave the building: next enter recomputes. Fog is not drawn while outside."""
        self._origin_cell = None
        if self.visible:
            self.visible = set()
            self.dirty = True

    def reveal_from(self, point):
        """Recompute visibility when `point` (world px, feet) enters a new grid cell."""
        col, row = self.world_to_cell(point)
        origin = self._anchor(col, row)
        if origin is None:
            if self.visible:
                self.visible = set()
                self._paint_unseen(self.visible)
            return
        if origin == self._origin_cell:
            return
        self._origin_cell = origin
        radius_cells = max(1, int(self.radius / self.cell))
        self.visible = visible_cells(self.walkable, origin, radius_cells)
        self._paint_unseen(self.visible)

    def consume_dirty(self):
        dirty = self.dirty
        self.dirty = False
        return dirty

    def _unseen_count(self):
        total = sum(1 for row in self.walkable for cell in row if cell)
        return total - len(self.visible)

    def _anchor(self, col, row):
        """Nearest walkable cell, so standing against a wall still has an origin."""
        if 0 <= col < self.cols and 0 <= row < self.rows and self.walkable[row][col]:
            return col, row
        for radius in range(1, 4):
            for dr in range(-radius, radius + 1):
                for dc in range(-radius, radius + 1):
                    nc, nr = col + dc, row + dr
                    if 0 <= nc < self.cols and 0 <= nr < self.rows and self.walkable[nr][nc]:
                        return nc, nr
        return None

    def _paint_unseen(self, visible):
        self.fog.fill((0, 0, 0, 0))
        cell = self.cell
        for row in range(self.rows):
            for col in range(self.cols):
                if self.walkable[row][col] and (col, row) not in visible:
                    self.fog.fill(FOG_RGBA, pygame.Rect(col * cell, row * cell, cell, cell))
        self.dirty = True
