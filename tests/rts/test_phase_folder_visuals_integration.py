import pygame

from rts.build.catalog import load_buildings
from rts.build.site import BuildSite
from rts.build.states import BUILDING, CLEARING_SNOW
from rts.categories import MATERIAL
from rts.entities import DropoffBuilding, ResourceNode, RtsWorker
from rts.gather.controller import GatherController
from rts.registry import RtsWorldRegistry
from rts.resources import ResourceWallet
from rts.tmx_config import dropoff_config, resource_node_config
from rts.world_sim import RtsWorldSim

from fakes import FakeWorldAdapter
from test_gather import _tick_gather


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


def test_build_site_visual_advances_during_clear_and_build(monkeypatch):
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    phase_calls = []

    class _TrackingVisual:
        def __init__(self, phases, fallback_size=(32, 32)):
            self.phase_index = 0
            self._started = False

        def reset(self):
            self.phase_index = 0
            self._started = False

        def start(self):
            self._started = True

        def is_complete(self):
            return self.phase_index >= 4

        def update(self, dt):
            if self._started:
                self.phase_index += 1
            return True

        def apply_to_sprite(self, sprite):
            phase_calls.append(self.phase_index)

    monkeypatch.setattr("rts.build.site.TimedPhaseVisual", _TrackingVisual)

    import rts.build.catalog as catalog_mod

    catalog_mod._buildings_cache = None
    building = load_buildings()["ice_cutting_post"]
    site = BuildSite(pygame.Rect(100, 100, 40, 40), "eskimo")
    site.setup_visual_from_building(building)
    site.start_visual()

    registry = RtsWorldRegistry()
    worker = RtsWorker(site.build_center, [], "eskimo", "worker_eskimo")
    adapter = _BuildSpawnAdapter(registry)
    sim = RtsWorldSim()
    sim.build_controller.registry = registry
    sim.build_controller.tasks[id(worker)] = worker
    worker.assigned_build_site = site
    worker.assigned_building_id = building.id
    worker.build_state = CLEARING_SNOW
    worker._build_timer = 10.0
    site.state = "clearing"
    site.start_visual()

    for _ in range(3):
        sim.build_controller.update(1.0, None)

    worker.build_state = BUILDING
    for _ in range(2):
        sim.build_controller.update(1.0, None)

    assert len(phase_calls) >= 3


def test_ice_shelf_drains_on_deliver():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    registry = RtsWorldRegistry()
    worker = RtsWorker((0, 0), [], "eskimo", "worker_eskimo")
    node_cfg = resource_node_config("ice_shelf", "eskimo")
    node_cfg["gather_duration"] = 0.05
    node = ResourceNode((40, 0), [], node_cfg, registry)
    assert node.ice_remaining == 100
    drop_cfg = dropoff_config("ice_cutting_post", "eskimo")
    dropoff = DropoffBuilding((0, 40), [], drop_cfg, registry)
    wallet = ResourceWallet()
    controller = GatherController(registry)
    controller.assign(worker, node, wallet)

    for _ in range(200):
        _tick_gather(controller, worker, 0.05, wallet=wallet)
        if node.ice_remaining < 100:
            break

    assert wallet.get(MATERIAL) >= 25
    assert node.ice_remaining == 75
