import time

import pygame

from game_logging import get_debug_logger
from navigation.grid_pathfinder import find_path
from navigation.unit_footprint import pathfinding_footprint_for_unit

from ..entities import DropoffBuilding, ResourceNode
from ..tmx_config import dropoff_config, resource_node_config
from .catalog import get_building

from .states import BUILD_IDLE, BUILD_LOST, BUILDING, CLEARING_SNOW, MOVING_TO_SITE

_rts_log = get_debug_logger("rts")
_MOVE_LOG_INTERVAL = 0.5
_REACH_RADIUS = 14.0


class BuildController:
    def __init__(self, registry=None):
        self.registry = registry
        self.tasks = {}
        self._on_build_complete = None
        self._wallet_resolver = None
        self._walk_grid_cache = None
        self._obstacle_quad_tree = None
        self._stuck_check = {}
        self._last_logged_state = {}
        self._move_log_next = {}

    def set_wallet_resolver(self, resolver):
        self._wallet_resolver = resolver

    def set_on_build_complete(self, callback):
        """Optional callback(worker, building, spawned_node) after a successful build."""
        self._on_build_complete = callback

    def set_navigation(self, walk_grid_cache=None, obstacle_quad_tree=None):
        if walk_grid_cache is not None:
            self._walk_grid_cache = walk_grid_cache
        if obstacle_quad_tree is not None:
            self._obstacle_quad_tree = obstacle_quad_tree

    def _grid_for_unit(self, unit):
        if self._walk_grid_cache is None:
            return None
        fw, fh = pathfinding_footprint_for_unit(unit)
        return self._walk_grid_cache.get(fw, fh)

    def _wallet_for_worker(self, worker):
        if self._wallet_resolver is not None and worker is not None:
            return self._wallet_resolver(getattr(worker, "faction_id", ""))
        return None

    def _log_state(self, worker, reason=""):
        wid = id(worker)
        state = getattr(worker, "build_state", "?")
        prev = self._last_logged_state.get(wid)
        if prev == state and reason not in ("assign", "at_site", "lost"):
            return
        self._last_logged_state[wid] = state
        site = getattr(worker, "assigned_build_site", None)
        _rts_log.debug(
            "build state=%s worker@%s reason=%s lost=%s site@%s building=%s",
            state,
            worker.rect.center,
            reason,
            getattr(worker, "build_lost", False),
            getattr(site, "build_center", None) if site else None,
            getattr(worker, "assigned_building_id", ""),
        )

    def _set_build_lost(self, worker, reason):
        worker.build_state = BUILD_LOST
        worker.build_lost = True
        worker.move_target = None
        self._log_state(worker, f"lost:{reason}")
        _rts_log.warning(
            "build LOST worker@%s reason=%s",
            getattr(worker, "rect", None) and worker.rect.center,
            reason,
        )

    def assign(self, worker, site, building_id, wallet=None, world_adapter=None):
        if worker is None or site is None:
            _rts_log.debug(
                "build assign rejected: worker=%s site=%s building_id=%s",
                worker,
                site,
                building_id,
            )
            return False
        if not site.is_available():
            _rts_log.debug(
                "build assign rejected: site unavailable worker@%s site@%s state=%s",
                worker.rect.center,
                site.build_center,
                getattr(site, "state", "?"),
            )
            return False
        building = get_building(building_id)
        if building is None:
            _rts_log.debug(
                "build assign rejected: unknown building_id=%s worker@%s",
                building_id,
                worker.rect.center,
            )
            return False
        if not building.matches_faction(worker.faction_id):
            _rts_log.debug(
                "build assign rejected: faction mismatch worker_faction=%s building=%s factions=%s",
                worker.faction_id,
                building.id,
                building.factions,
            )
            return False
        if site.requires and building.placement_requires != site.requires:
            _rts_log.debug(
                "build assign rejected: placement_requires site=%s building=%s",
                site.requires,
                building.placement_requires,
            )
            return False
        w = wallet or self._wallet_for_worker(worker)
        if w is not None and not w.can_afford(building.cost):
            _rts_log.debug(
                "build assign rejected: cant_afford worker@%s building=%s cost=%s",
                worker.rect.center,
                building.id,
                building.cost,
            )
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
        self._move_log_next.pop(id(worker), None)
        self._stuck_check.pop(id(worker), None)
        if hasattr(site, "setup_visual_from_building"):
            site.setup_visual_from_building(building)

        goal = site.build_center
        path_len = 0
        if self._walk_grid_cache is not None:
            if not self._plan_path(worker, goal):
                self._set_build_lost(worker, "no_path_on_assign")
                return False
            path_len = len(getattr(worker, "_build_path", None) or [])
        self._log_state(worker, "assign")
        _rts_log.debug(
            "build assign ok worker@%s faction=%s -> site@%s building=%s "
            "site_state=%s path_len=%s walk_grid_cache=%s",
            worker.rect.center,
            worker.faction_id,
            goal,
            building.id,
            getattr(site, "state", "?"),
            path_len,
            self._walk_grid_cache is not None,
        )
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
        worker.move_target = None
        self.tasks.pop(id(worker), None)
        self._last_logged_state.pop(id(worker), None)
        self._stuck_check.pop(id(worker), None)
        self._move_log_next.pop(id(worker), None)
        _rts_log.debug(
            "build cancel worker@%s",
            getattr(worker, "rect", None) and worker.rect.center,
        )

    def update(self, dt, obstacle_sprites=None, walk_grid_cache=None, obstacle_quad_tree=None):
        if walk_grid_cache is not None:
            self._walk_grid_cache = walk_grid_cache
        if obstacle_quad_tree is not None:
            self._obstacle_quad_tree = obstacle_quad_tree
        for worker in list(self.tasks.values()):
            self._step_worker(worker, float(dt or 0), obstacle_sprites)

    def _plan_path(self, worker, goal_px):
        grid = self._grid_for_unit(worker)
        if grid is None:
            worker._build_path = []
            worker._build_path_index = 0
            _rts_log.warning(
                "build path failed worker@%s -> %s (no walk grid for footprint)",
                worker.rect.center,
                goal_px,
            )
            return False
        path = find_path(grid, worker.rect.center, goal_px)
        if not path:
            worker._build_path = []
            worker._build_path_index = 0
            _rts_log.warning(
                "build path failed worker@%s -> %s",
                worker.rect.center,
                goal_px,
            )
            return False
        path[-1] = pygame.math.Vector2(goal_px[0], goal_px[1])
        worker._build_path = path
        worker._build_path_index = 0
        self._stuck_check[id(worker)] = (
            time.monotonic(),
            pygame.math.Vector2(worker.rect.center),
        )
        _rts_log.debug(
            "build path plan %d waypoints worker@%s -> %s",
            len(path),
            worker.rect.center,
            goal_px,
        )
        return True

    def _should_log_move(self, worker, key, interval=_MOVE_LOG_INTERVAL):
        wid = id(worker)
        now = time.monotonic()
        bucket = self._move_log_next.setdefault(wid, {})
        if now < bucket.get(key, 0.0):
            return False
        bucket[key] = now + interval
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
                if self._should_log_move(worker, "to_site_waypoint", interval=1.0):
                    _rts_log.debug(
                        "build waypoint advance %d/%d worker@%s",
                        idx + 1,
                        len(path),
                        worker.rect.center,
                    )
                self._stuck_check[id(worker)] = (
                    time.monotonic(),
                    pygame.math.Vector2(worker.rect.center),
                )
                worker.move_target = None
                return False
            if self._should_log_move(worker, "to_site_arrived", interval=1.0):
                _rts_log.debug(
                    "move to_site ARRIVED worker@%s goal=%s",
                    worker.rect.center,
                    target,
                )
            worker.move_target = None
            return True
        worker.move_target = pygame.math.Vector2(target)
        if self._should_log_move(worker, "to_site"):
            _rts_log.debug(
                "move to_site worker@%s -> %s dist=%.1f move_target=%s",
                worker.rect.center,
                target,
                dist_sq**0.5,
                (int(worker.move_target.x), int(worker.move_target.y)),
            )
        return False

    def _step_worker(self, worker, dt, obstacle_sprites):
        site = worker.assigned_build_site
        state = worker.build_state
        if state == BUILD_LOST:
            return
        if site is None:
            self._set_build_lost(worker, "missing_site")
            return

        building = get_building(worker.assigned_building_id)
        if building is None:
            self._set_build_lost(worker, "missing_building_def")
            return

        if state == MOVING_TO_SITE:
            if getattr(worker, "move_target", None) is None and self._should_log_move(
                worker, "no_move_target", interval=2.0
            ):
                _rts_log.warning(
                    "build MOVING_TO_SITE but move_target is None worker@%s site@%s",
                    worker.rect.center,
                    site.build_center,
                )
            if self._move_along_path(worker, site.build_center, dt, obstacle_sprites):
                worker.build_state = CLEARING_SNOW
                worker._build_timer = building.clear_duration_ms / 1000.0
                site.state = "clearing"
                if hasattr(site, "start_visual"):
                    site.start_visual()
                self._log_state(worker, "at_site")
            return

        if state == CLEARING_SNOW:
            worker.move_target = None
            if hasattr(site, "update_visual"):
                site.update_visual(dt)
            worker._build_timer -= dt
            if worker._build_timer <= 0:
                worker.build_state = BUILDING
                worker._build_timer = building.build_duration_ms / 1000.0
                from .site import SITE_BUILDING

                site.state = SITE_BUILDING
                self._log_state(worker, "building")
            return

        if state == BUILDING:
            worker.move_target = None
            if hasattr(site, "update_visual"):
                site.update_visual(dt)
            worker._build_timer -= dt
            if worker._build_timer <= 0:
                self._complete_build(worker, site, building)
            return

    def _retire_build_site(self, site, adapter, registry):
        if registry is not None:
            registry.unregister_build_site(site)
        if hasattr(adapter, "level"):
            lm = adapter.level.layout_manager
            env = getattr(lm, "environment_interactables", None)
            if env is not None and site in env:
                env.remove(site)
        site.kill()

    def _complete_build(self, worker, site, building):
        wallet = self._wallet_for_worker(worker)
        if wallet is not None and building.cost:
            if not wallet.spend(building.cost):
                self._set_build_lost(worker, "spend_failed")
                return

        adapter = getattr(worker, "_build_world_adapter", None)
        if adapter is None:
            self._set_build_lost(worker, "missing_world_adapter")
            return

        registry = adapter.get_rts_registry()
        groups = adapter.get_sprite_groups()
        center = site.build_center
        fid = worker.faction_id

        spawned_obstacles = []
        spawned_node = None
        if building.spawn_node_kind:
            node_cfg = resource_node_config(building.spawn_node_kind, fid)
            spawned_node = ResourceNode(center, groups, node_cfg, registry)
            spawned_obstacles.append(spawned_node)

        if building.spawn_dropoff_kind:
            drop_cfg = dropoff_config(building.spawn_dropoff_kind, fid)
            dropoff = DropoffBuilding(center, groups, drop_cfg, registry)
            spawned_obstacles.append(dropoff)

        if hasattr(adapter, "level"):
            lm = adapter.level.layout_manager
            for spawned in spawned_obstacles:
                lm.environment_interactables.append(spawned)
                lm.register_obstacle_sprite(spawned, live=True)

        self._retire_build_site(site, adapter, registry)

        from .site import SITE_COMPLETED

        site.state = SITE_COMPLETED
        worker.build_state = BUILD_IDLE
        worker.assigned_build_site = None
        worker.assigned_building_id = ""
        worker._build_world_adapter = None
        worker.move_target = None
        self.tasks.pop(id(worker), None)
        self._last_logged_state.pop(id(worker), None)
        _rts_log.debug(
            "build complete worker@%s site@%s building=%s dropoff=%s node=%s",
            worker.rect.center,
            center,
            building.id,
            building.spawn_dropoff_kind,
            building.spawn_node_kind,
        )
        if self._on_build_complete is not None:
            self._on_build_complete(worker, building, spawned_node)
