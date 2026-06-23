import pygame

from rts.build.states import BUILD_IDLE, CLEARING_SNOW
from rts.build.site import BuildSite
from rts.entities import DropoffBuilding, RtsWorker
from rts.entities.gather_states import MOVING_TO_NODE
from rts.registry import RtsWorldRegistry
from rts.resources import ResourceWallet
from rts.tmx_config import dropoff_config
from rts.world_sim import RtsWorldSim

from fakes import FakeWorldAdapter


class _BuildSpawnAdapter(FakeWorldAdapter):
    def __init__(self, registry):
        super().__init__()
        self._rts_registry = registry
        self.env = []

        class _LM:
            def register_obstacle_sprite(self, sprite, live=True):
                pass

        lm = _LM()
        lm.environment_interactables = self.env
        self.level = type("Level", (), {"layout_manager": lm})()


def test_build_complete_spawns_ice_shelf_gather_node_only():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    registry = RtsWorldRegistry()
    site = BuildSite(pygame.Rect(200, 200, 50, 50), "eskimo", requires="deep_snow")
    registry.register_build_site(site)
    worker = RtsWorker(site.build_center, [], "eskimo", "worker_eskimo")
    registry.register_worker(worker)

    adapter = _BuildSpawnAdapter(registry)
    wallet = ResourceWallet()
    drop_cfg = dropoff_config("ice_cutting_post", "eskimo")
    DropoffBuilding((200, 280), [], drop_cfg, registry)
    sim = RtsWorldSim()
    sim.build_controller.registry = registry
    sim.gather_controller.registry = registry
    sim.assign_build(worker, site, "ice_cutting_post", wallet=wallet, world_adapter=adapter)

    worker.rect.center = site.build_center
    worker.build_state = CLEARING_SNOW
    worker._build_timer = 0.001

    for _ in range(4):
        sim.build_controller.update(5.0, None)

    assert len(registry.dropoffs_for_kind("eskimo", "ice_cutting_post")) == 1
    nodes = registry.nodes_for_faction("eskimo", "material")
    assert any(getattr(n, "node_kind", "") == "ice_shelf" for n in nodes)
    assert site not in registry.build_sites_by_faction.get("eskimo", [])
    assert site not in adapter.env
    assert not site.alive()
    assert worker.build_state == BUILD_IDLE
    assert id(worker) in sim.gather_controller.tasks
    assert worker.assigned_node is not None
    assert worker.assigned_node.node_kind == "ice_shelf"
    assert worker.gather_state == MOVING_TO_NODE
