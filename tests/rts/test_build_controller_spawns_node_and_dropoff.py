import pygame

from rts.build.states import BUILD_IDLE, CLEARING_SNOW
from rts.build.site import BuildSite
from rts.entities import DropoffBuilding, ResourceNode, RtsWorker
from rts.registry import RtsWorldRegistry
from rts.resources import ResourceWallet
from rts.world_sim import RtsWorldSim

from fakes import FakeWorldAdapter


class _BuildSpawnAdapter(FakeWorldAdapter):
    def __init__(self, registry):
        super().__init__()
        self._rts_registry = registry
        self.env = []

        class _LM:
            pass

        lm = _LM()
        lm.environment_interactables = self.env
        self.level = type("Level", (), {"layout_manager": lm})()


def test_build_complete_spawns_ice_cutting_post_and_shelf():
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
    sim = RtsWorldSim()
    sim.build_controller.registry = registry
    sim.assign_build(worker, site, "ice_cutting_post", wallet=wallet, world_adapter=adapter)

    worker.rect.center = site.build_center
    worker.build_state = CLEARING_SNOW
    worker._build_timer = 0.001

    for _ in range(4):
        sim.build_controller.update(5.0, None)

    assert registry.find_dropoff("eskimo", "ice_cutting_post") is not None
    nodes = registry.nodes_for_faction("eskimo")
    assert any(getattr(n, "node_kind", "") == "ice_shelf" for n in nodes)
    assert not site.is_available()
    assert worker.build_state == BUILD_IDLE
