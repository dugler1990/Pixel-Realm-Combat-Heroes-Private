"""Conservative broad-phase grid for effect zone presence."""


class EffectCellGrid:
    """Boolean occupancy grid: True where any effect area rect overlaps a cell."""

    __slots__ = ("_cells", "cols", "rows", "cell_size")

    def __init__(self, cells, cols, rows, cell_size):
        self._cells = cells
        self.cols = int(cols)
        self.rows = int(rows)
        self.cell_size = int(cell_size)

    @classmethod
    def build(cls, effect_areas, cell_size, world_w, world_h):
        if not effect_areas:
            return None
        cell_size = max(1, int(cell_size))
        cols = max(1, (int(world_w) + cell_size - 1) // cell_size)
        rows = max(1, (int(world_h) + cell_size - 1) // cell_size)
        cells = bytearray(cols * rows)
        for area in effect_areas:
            cls._mark_rect(cells, cols, rows, cell_size, area.rect)
        return cls(cells, cols, rows, cell_size)

    @staticmethod
    def _mark_rect(cells, cols, rows, cell_size, rect):
        c0, c1, r0, r1 = EffectCellGrid._cell_range(rect, cell_size, cols, rows)
        for row in range(r0, r1 + 1):
            base = row * cols
            for col in range(c0, c1 + 1):
                cells[base + col] = 1

    @staticmethod
    def _cell_range(rect, cell_size, cols, rows):
        c0 = max(0, rect.left // cell_size)
        c1 = min(cols - 1, max(c0, (rect.right - 1) // cell_size))
        r0 = max(0, rect.top // cell_size)
        r1 = min(rows - 1, max(r0, (rect.bottom - 1) // cell_size))
        return c0, c1, r0, r1

    def intersects_rect(self, rect):
        c0, c1, r0, r1 = self._cell_range(rect, self.cell_size, self.cols, self.rows)
        for row in range(r0, r1 + 1):
            base = row * self.cols
            for col in range(c0, c1 + 1):
                if self._cells[base + col]:
                    return True
        return False
