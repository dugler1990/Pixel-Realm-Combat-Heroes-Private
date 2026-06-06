"""Cached walk grids keyed by unit mask footprint; prewarmed at map load."""

import logging

from .nav_sizing import nav_grid_params
from .unit_footprint import pathfinding_footprint_for_monster, rts_worker_monster_names
from .walk_grid import block_walk_grid_cells_for_item, build_walk_grid

_log = logging.getLogger(__name__)


class WalkGridCache:
    def __init__(self, obstacle_quad_tree, world_width, world_height):
        self._qt = obstacle_quad_tree
        self._ww = int(world_width)
        self._wh = int(world_height)
        self._grids = {}

    def prewarm_at_load(self, footprints):
        for fw, fh in footprints:
            self._build_if_missing(fw, fh)

    def prewarm_rts_workers(self):
        fps = []
        for name in rts_worker_monster_names():
            size = pathfinding_footprint_for_monster(name)
            if size not in fps:
                fps.append(size)
        self.prewarm_at_load(fps)

    def get(self, footprint_w, footprint_h):
        key = (int(footprint_w), int(footprint_h))
        grid = self._grids.get(key)
        if grid is None:
            _log.warning(
                "WalkGridCache miss for footprint %s (not prewarmed at load)",
                key,
            )
        return grid

    def _build_if_missing(self, fw, fh):
        key = (int(fw), int(fh))
        if key in self._grids:
            return
        cell_w, cell_h, probe_w, probe_h = nav_grid_params(key[0], key[1])
        self._grids[key] = build_walk_grid(
            self._qt,
            self._ww,
            self._wh,
            cell_w,
            cell_h,
            probe_w=probe_w,
            probe_h=probe_h,
        )

    def block_walk_grid_cells_for_item(self, item):
        """Patch prewarmed pathfinding grids for one new static obstacle item."""
        if item is None or not self._grids:
            return
        for key, grid in self._grids.items():
            cell_w, cell_h, probe_w, probe_h = nav_grid_params(key[0], key[1])
            block_walk_grid_cells_for_item(
                grid, item, cell_w, cell_h, probe_w, probe_h
            )
