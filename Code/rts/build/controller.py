import time

import pygame

from game_logging import get_debug_logger
from navigation.grid_pathfinder import find_path
from navigation.quad_mover import step_toward

from ..entities import DropoffBuilding, ResourceNode
from ..tmx_config import dropoff_config, resource_node_config
from .catalog import get_building

from .states import BUILD_IDLE, BUILD_LOST, BUILDING, CLEARING_SNOW, MOVING_TO_SITE

_rts_log = get_debug_logger("rts")
_REACH_RADIUS = 14.0


class BuildController:
    def __init__(self, registry=None):
        self.registry = registry
        self.tasks = {}
        self._wallet_resolver = None
        self._walk_grid = None
        self._obstacle_quad_tree = None
        self._stuck_check = {}

    def set_wallet_resolver(self, resolver):
        self._wallet_resolver = resolver

    def set_navigation(self, walk_grid=None, obstacle_quad_tree=None):
        if walk_grid is not None:
            self._walk_grid = walk_grid
        if obstacle_quad_tree is not None:
            self._obstacle_quad_tree = obstacle_quad_tree

    def _wallet_for_worker(self, worker):
        if self._wallet_resolver is not None and worker is not None:
            return self._wallet_resolver(getattr(worker, "faction_id", ""))
        return None

    def assign(self, worker, site, building_id, wallet=None, world_adapter=None):
        if worker is None or site is None:
            return False
        if not site.is_available():
            return False
        building = get_building(building_id)
        if building is None:
            return False
        if not building.matches_faction(worker.faction_id):
            return False
        if site.requires and building.placement_requires != site.requires:
            return False
        w = wallet or self._wallet_for_worker(worker)
        if w is not None and not w.can_afford(building.cost):
            return False

        worker.assigned_build_site = site
        worker.assigned_building_id = building.id
        worker.build_lost = False
        worker.build_state = MOVING_TO_SITE
        worker._build_timer = 0.0
        worker._build_path = []
        worker._build_path_index = 0
        worker._build_path_planned = False
        worker._build_world_adapter = world_adapter
        self.tasks[id(worker)] = worker
        self._stuck_check.pop(id(worker), None)

        goal = site.build_center
        if self._walk_grid is not None and not self._plan_path(worker, goal):
            worker.build_state = BUILD_LOST
            worker.build_lost = True
            return False
        return True

    def cancel(self, worker):
        if worker is None:
            return
        worker.assigned_build_site = None
        worker.assigned_building_id = ""
        worker.build_state = BUILD_IDLE
        worker.build_lost = False
        worker._build_path = []
        worker._build_path_index = 0
        worker._build_path_planned = False
        worker._build_world_adapter = None
        self.tasks.pop(id(worker), None)
        self._stuck_check.pop(id(worker), None)

    def update(self, dt, obstacle_sprites=None, walk_grid=None, obstacle_quad_tree=None):
        if walk_grid is not None:
            self._walk_grid = walk_grid
        if obstacle_quad_tree is not None:
            self._obstacle_quad_tree = obstacle_quad_tree
        for worker in list(self.tasks.values()):
            self._step_worker(worker, float(dt or 0), obstacle_sprites)

    def _plan_path(self, worker, goal_px):
        if self._walk_grid is None:
            worker._build_path = []
            worker._build_path_index = 0
            return True
        path = find_path(self._walk_grid, worker.rect.center, goal_px)
        if not path:
            worker._build_path = []
            worker._build_path_index = 0
            return False
        path[-1] = pygame.math.Vector2(goal_px[0], goal_px[1])
        worker._build_path = path
        worker._build_path_index = 0
        self._stuck_check[id(worker)] = (time.monotonic(), pygame.math.Vector2(worker.rect.center))
        return True

    def _move_along_path(self, worker, final_goal, dt, obstacle_sprites):
        path = getattr(worker, "_build_path", None) or []
        idx = int(getattr(worker, "_build_path_index", 0))
        on_last = path and idx >= len(path) - 1
        if path and idx < len(path) and not on_last:
            target = (int(path[idx].x), int(path[idx].y))
        elif on_last and final_goal is not None:
            target = final_goal
        else:
            target = final_goal
        if target is None:
            return False
        dx = target[0] - worker.rect.centerx
        dy = target[1] - worker.rect.centery
        dist_sq = dx * dx + dy * dy
        if dist_sq <= _REACH_RADIUS * _REACH_RADIUS:
            if path and idx < len(path) - 1:
                worker._build_path_index = idx + 1
            return True
        speed = getattr(worker, "speed", 120.0)
        step_toward(
            worker,
            target,
            speed,
            dt,
            obstacle_sprites,
            self._obstacle_quad_tree,
            skip_sprites=[worker],
        )
        return False

    def _step_worker(self, worker, dt, obstacle_sprites):
        site = worker.assigned_build_site
        state = worker.build_state
        if state == BUILD_LOST:
            return
        if site is None:
            worker.build_state = BUILD_LOST
            worker.build_lost = True
            return

        building = get_building(worker.assigned_building_id)
        if building is None:
            worker.build_state = BUILD_LOST
            worker.build_lost = True
            return

        if state == MOVING_TO_SITE:
            if self._move_along_path(worker, site.build_center, dt, obstacle_sprites):
                worker.build_state = CLEARING_SNOW
                worker._build_timer = building.clear_duration_ms / 1000.0
                site.state = "clearing"
            return

        if state == CLEARING_SNOW:
            worker._build_timer -= dt
            if worker._build_timer <= 0:
                worker.build_state = BUILDING
                worker._build_timer = building.build_duration_ms / 1000.0
                from .site import SITE_BUILDING

                site.state = SITE_BUILDING
            return

        if state == BUILDING:
            worker._build_timer -= dt
            if worker._build_timer <= 0:
                self._complete_build(worker, site, building)
            return

    def _complete_build(self, worker, site, building):
        wallet = self._wallet_for_worker(worker)
        if wallet is not None and building.cost:
            if not wallet.spend(building.cost):
                worker.build_state = BUILD_LOST
                worker.build_lost = True
                return

        adapter = getattr(worker, "_build_world_adapter", None)
        if adapter is None:
            worker.build_state = BUILD_LOST
            worker.build_lost = True
            return

        registry = adapter.get_rts_registry()
        groups = adapter.get_sprite_groups()
        center = site.build_center
        fid = worker.faction_id

        if building.spawn_dropoff_kind:
            drop_cfg = dropoff_config(building.spawn_dropoff_kind, fid)
            dropoff = DropoffBuilding(center, groups, drop_cfg, registry)
            if hasattr(adapter, "level"):
                lm = adapter.level.layout_manager
                lm.environment_interactables.append(dropoff)

        if building.spawn_node_kind:
            node_cfg = resource_node_config(building.spawn_node_kind, fid)
            node = ResourceNode(center, groups, node_cfg, registry)
            if hasattr(adapter, "level"):
                lm = adapter.level.layout_manager
                lm.environment_interactables.append(node)

        from .site import SITE_COMPLETED

        site.state = SITE_COMPLETED
        worker.build_state = BUILD_IDLE
        worker.assigned_build_site = None
        worker.assigned_building_id = ""
        worker._build_world_adapter = None
        self.tasks.pop(id(worker), None)
        _rts_log.debug(
            "build complete site@%s building=%s dropoff=%s node=%s",
            center,
            building.id,
            building.spawn_dropoff_kind,
            building.spawn_node_kind,
        )
