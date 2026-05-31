"""Fixed gather positions around a resource node (e.g. ice shelf)."""

import pygame


def build_gather_slot_positions(center, count, *, cols=5, spacing=22, front_offset_y=18):
    """
    Lay out `count` world positions in a shallow grid south of `center`.
    `center` is (x, y) — typically the node gather anchor.
    """
    cx, cy = int(center[0]), int(center[1])
    rows = max(1, (count + cols - 1) // cols)
    slots = []
    for index in range(count):
        row = index // cols
        col = index % cols
        row_count = min(cols, count - row * cols)
        ox = (col - (row_count - 1) / 2.0) * spacing
        oy = front_offset_y + row * spacing
        slots.append((int(cx + ox), int(cy + oy)))
    return slots


class GatherSlotBook:
    """Tracks which gather slot index each worker owns on a node."""

    def __init__(self, positions):
        self.positions = list(positions)
        self._owners = [None] * len(self.positions)

    def has_free(self):
        return any(owner is None for owner in self._owners)

    def goal_for(self, worker):
        wid = id(worker)
        for index, owner in enumerate(self._owners):
            if owner == wid:
                return self.positions[index]
        return None

    def claim(self, worker):
        wid = id(worker)
        existing = self.goal_for(worker)
        if existing is not None:
            return existing
        for index, owner in enumerate(self._owners):
            if owner is None:
                self._owners[index] = wid
                return self.positions[index]
        return None

    def release(self, worker):
        wid = id(worker)
        for index, owner in enumerate(self._owners):
            if owner == wid:
                self._owners[index] = None
                return
