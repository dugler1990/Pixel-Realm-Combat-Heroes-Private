from collections import defaultdict

import pygame

from QuadTree import QuadTree, QuadTreeManager
from benchmark_runtime import BENCHMARK_RUNTIME


def _benchmark_metrics_active():
    return BENCHMARK_RUNTIME.enabled and BENCHMARK_RUNTIME.metrics_enabled


def _record_benchmark_maintenance(op):
    if _benchmark_metrics_active():
        BENCHMARK_RUNTIME.metrics.record_maintenance(op)


def _record_benchmark_query(candidates):
    if _benchmark_metrics_active():
        BENCHMARK_RUNTIME.metrics.record_query(candidates)


class DynamicUniformGridBroadphase:
    def __init__(self, world_rect: pygame.Rect, cell_size: int = 300):
        self.world_rect = pygame.Rect(world_rect)
        self.cell_size = max(1, int(cell_size))
        self._cells = defaultdict(set)  # (cx, cy) -> set(item_id)
        self._item_cells = {}  # item_id -> set((cx, cy))
        self._items = {}  # item_id -> HashableRect-like

    def _cell_coords_for_rect(self, rect: pygame.Rect):
        left, right, top, bottom = self._cell_bounds_for_rect(rect)
        cells = set()
        for cx in range(left, right + 1):
            for cy in range(top, bottom + 1):
                cells.add((cx, cy))
        return cells

    def _cell_bounds_for_rect(self, rect: pygame.Rect):
        cell_size = self.cell_size
        left = int(rect.left // cell_size)
        right = int(rect.right // cell_size)
        top = int(rect.top // cell_size)
        bottom = int(rect.bottom // cell_size)
        return left, right, top, bottom

    def upsert(self, item):
        item_id = item._id
        new_cells = self._cell_coords_for_rect(item.rect)
        old_cells = self._item_cells.get(item_id, set())

        if old_cells != new_cells:
            for cell in old_cells:
                bucket = self._cells.get(cell)
                if bucket is not None:
                    bucket.discard(item_id)
                    if not bucket:
                        del self._cells[cell]
            for cell in new_cells:
                self._cells[cell].add(item_id)
            self._item_cells[item_id] = new_cells

        self._items[item_id] = item
        _record_benchmark_maintenance("upsert")

    def remove(self, item_id):
        old_cells = self._item_cells.pop(item_id, set())
        for cell in old_cells:
            bucket = self._cells.get(cell)
            if bucket is not None:
                bucket.discard(item_id)
                if not bucket:
                    del self._cells[cell]
        self._items.pop(item_id, None)
        _record_benchmark_maintenance("remove")

    def query(self, query_rect, query_id=-1):
        candidates = set()
        query_rect_rect = query_rect.rect
        cells = self._cells
        items = self._items
        left, right, top, bottom = self._cell_bounds_for_rect(query_rect_rect)
        for cx in range(left, right + 1):
            for cy in range(top, bottom + 1):
                for item_id in cells.get((cx, cy), ()):
                    if item_id == query_id:
                        continue
                    item = items.get(item_id)
                    if item is not None and item.rect.colliderect(query_rect_rect):
                        candidates.add(item)
        _record_benchmark_query(len(candidates))
        return candidates


class DynamicQuadtreeBroadphase:
    def __init__(self, world_rect: pygame.Rect):
        self.manager = QuadTreeManager()
        self.tree = QuadTree(items=[], depth=8, bounding_rect=world_rect, manager=self.manager)

    def upsert(self, item):
        self.tree.insert(item, alive=True, remove_existing=True)
        _record_benchmark_maintenance("upsert")

    def remove(self, item_id):
        self.manager.remove(item_id, remove_existing=True)
        _record_benchmark_maintenance("remove")

    def query(self, query_rect, query_id=-1):
        hits = self.tree.hit(query_rect)
        _record_benchmark_query(len(hits))
        return hits


class MovingEntityBroadphaseAdapter:
    """Adapter preserving the old .insert/.hit calls used by entities."""

    def __init__(self, world_rect: pygame.Rect, backend: str = "quadtree", grid_cell_size: int = 300):
        self.world_rect = pygame.Rect(world_rect)
        self.backend_name = ""
        self.backend = None
        self.grid_cell_size = max(1, int(grid_cell_size))
        self.set_backend(backend, grid_cell_size=self.grid_cell_size)

    def set_backend(self, backend: str, current_items=None, grid_cell_size: int | None = None):
        backend = (backend or "quadtree").lower()
        if backend not in ("quadtree", "grid"):
            backend = "quadtree"
        if grid_cell_size is not None:
            self.grid_cell_size = max(1, int(grid_cell_size))

        self.backend_name = backend
        if BENCHMARK_RUNTIME.enabled:
            BENCHMARK_RUNTIME.broadphase_backend = backend
        if backend == "grid":
            self.backend = DynamicUniformGridBroadphase(
                self.world_rect,
                cell_size=self.grid_cell_size,
            )
        else:
            self.backend = DynamicQuadtreeBroadphase(self.world_rect)

        if current_items:
            for item in current_items:
                self.backend.upsert(item)

    # Legacy API compatibility
    def hit(self, rect):
        return self.backend.query(rect, query_id=getattr(rect, "_id", -1))

    def query(self, rect, item_id=-1):
        return self.backend.query(rect, query_id=item_id)

    def insert(self, item, alive=True, remove_existing=True):
        if remove_existing:
            self.backend.remove(item._id)
        if alive:
            self.backend.upsert(item)

    def upsert(self, entity):
        self.backend.upsert(entity)

    def remove(self, item_id):
        self.backend.remove(item_id)
