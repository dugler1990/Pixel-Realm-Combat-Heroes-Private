"""Persistent RTS world simulation (economy, gather, upkeep) independent of throne UI."""

from game_logging import get_debug_logger

from .assets import normalize_faction_id
from .build import BuildController
from .factions import get_profile
from .gather import GatherController
from .resources import ResourceWallet
from .upkeep import FoodUpkeep

_rts_log = get_debug_logger("rts")


class RtsWorldSim:
    def __init__(self):
        self.gather_controller = GatherController()
        self.gather_controller.set_wallet_resolver(self.get_wallet)
        self.build_controller = BuildController()
        self.build_controller.set_wallet_resolver(self.get_wallet)
        self.build_controller.set_on_build_complete(self._on_build_completed)
        self._wallets = {}
        self._food_upkeep = {}

    def get_wallet(self, faction_id):
        fid = normalize_faction_id(faction_id)
        if not fid:
            return None
        if fid not in self._wallets:
            profile = get_profile(fid)
            categories = profile.active_categories if profile is not None else None
            self._wallets[fid] = ResourceWallet(categories)
            _rts_log.debug("wallet created faction=%s wallet_id=%s", fid, id(self._wallets[fid]))
        return self._wallets[fid]

    def ensure_factions_from_registry(self, registry):
        if registry is None:
            return
        for chief in registry.chiefs.values():
            self.get_wallet(getattr(chief, "faction_id", ""))
        for fid in registry.workers_by_faction:
            self.get_wallet(fid)
        for fid in registry.faction_node_index:
            self.get_wallet(fid)
        for fid in registry.build_sites_by_faction:
            self.get_wallet(fid)

    def bind_navigation(self, world_adapter):
        walk_grid = world_adapter.get_walk_grid()
        obstacle_quad_tree = world_adapter.get_obstacle_quad_tree()
        self.gather_controller.set_navigation(walk_grid, obstacle_quad_tree)
        self.build_controller.set_navigation(walk_grid, obstacle_quad_tree)

    def cancel_worker_jobs(self, worker):
        self.gather_controller.cancel(worker)
        self.build_controller.cancel(worker)

    def assign_gather(self, worker, node, wallet=None):
        self.build_controller.cancel(worker)
        return self.gather_controller.assign(worker, node, wallet)

    def _on_build_completed(self, worker, building, spawned_node):
        if spawned_node is None:
            return
        wallet = self.get_wallet(getattr(worker, "faction_id", ""))
        ok = self.assign_gather(worker, spawned_node, wallet)
        _rts_log.debug(
            "auto gather after build ok=%s worker@%s building=%s node=%s",
            ok,
            getattr(worker, "rect", None) and worker.rect.center,
            getattr(building, "id", ""),
            getattr(spawned_node, "node_kind", ""),
        )

    def assign_build(self, worker, site, building_id, wallet=None, world_adapter=None):
        worker_pos = getattr(worker, "rect", None) and worker.rect.center
        site_pos = getattr(site, "build_center", None) if site is not None else None
        _rts_log.debug(
            "assign_build request worker@%s site@%s building_id=%s site_state=%s",
            worker_pos,
            site_pos,
            building_id,
            getattr(site, "state", None) if site is not None else None,
        )
        self.gather_controller.cancel(worker)
        ok = self.build_controller.assign(
            worker, site, building_id, wallet=wallet, world_adapter=world_adapter
        )
        _rts_log.debug(
            "assign_build result ok=%s worker@%s site@%s building_id=%s",
            ok,
            worker_pos,
            site_pos,
            building_id,
        )
        return ok

    def food_upkeep_for(self, faction_id):
        fid = normalize_faction_id(faction_id)
        return self._food_upkeep.setdefault(fid, FoodUpkeep())

    def low_food_for_faction(self, faction_id):
        upkeep = self._food_upkeep.get(normalize_faction_id(faction_id))
        return bool(upkeep and upkeep.low_food)

    def on_worker_death(self, worker):
        self.cancel_worker_jobs(worker)
        registry = self.gather_controller.registry
        if registry is not None:
            registry.unregister_worker(worker)
        chief = getattr(worker, "chief", None)
        if chief is not None:
            spawned = getattr(chief, "spawned_workers", None)
            if spawned is not None and worker in spawned:
                spawned.remove(worker)
                chief.population_workers = max(0, int(chief.population_workers) - 1)

    def tick(self, dt, world_adapter):
        """Run gather/build FSM and set worker move_target before level Entity.update moves units."""
        registry = world_adapter.get_rts_registry()
        if registry is None:
            return

        self.gather_controller.registry = registry
        self.build_controller.registry = registry
        self.ensure_factions_from_registry(registry)

        obstacles = world_adapter.get_obstacle_sprites()
        for fac_nodes in registry.faction_node_index.values():
            for cat_list in fac_nodes.values():
                for node in cat_list:
                    node.update(dt)

        walk_grid = world_adapter.get_walk_grid()
        obstacle_quad_tree = world_adapter.get_obstacle_quad_tree()
        self.gather_controller.update(
            dt,
            obstacles,
            walk_grid=walk_grid,
            obstacle_quad_tree=obstacle_quad_tree,
        )
        self.build_controller.update(
            dt,
            obstacles,
            walk_grid=walk_grid,
            obstacle_quad_tree=obstacle_quad_tree,
        )

        for fid, workers in registry.workers_by_faction.items():
            if not workers:
                continue
            wallet = self.get_wallet(fid)
            if wallet is None:
                continue
            profile = get_profile(fid)
            rate = (
                profile.food_upkeep_per_unit_per_min
                if profile is not None
                else 0.5
            )
            self.food_upkeep_for(fid).update(dt, wallet, len(workers), rate)
