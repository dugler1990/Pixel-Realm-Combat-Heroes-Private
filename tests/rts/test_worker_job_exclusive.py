import pygame

from rts.build.site import BuildSite
from rts.entities import DropoffBuilding, ResourceNode, RtsWorker
from rts.gather.controller import GatherController
from rts.registry import RtsWorldRegistry
from rts.tmx_config import dropoff_config, resource_node_config
from rts.world_sim import RtsWorldSim

from fakes import FakeWorldAdapter


def test_build_assign_cancels_gather():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    registry = RtsWorldRegistry()
    worker = RtsWorker((0, 0), [], "eskimo", "worker_eskimo")
    node_cfg = resource_node_config("ice_shelf", "eskimo")
    node = ResourceNode((40, 0), [], node_cfg, registry)
    drop_cfg = dropoff_config("ice_cutting_post", "eskimo")
    DropoffBuilding((0, 40), [], drop_cfg, registry)
    site = BuildSite(pygame.Rect(100, 100, 40, 40), "eskimo")
    registry.register_build_site(site)

    sim = RtsWorldSim()
    sim.gather_controller.registry = registry
    sim.build_controller.registry = registry
    sim.assign_gather(worker, node, sim.get_wallet("eskimo"))
    assert id(worker) in sim.gather_controller.tasks

    adapter = FakeWorldAdapter()
    adapter._rts_registry = registry
    sim.assign_build(worker, site, "ice_cutting_post", world_adapter=adapter)

    assert id(worker) not in sim.gather_controller.tasks
    assert id(worker) in sim.build_controller.tasks


def test_gather_assign_cancels_build():
    registry = RtsWorldRegistry()
    worker = RtsWorker((0, 0), [], "eskimo", "worker_eskimo")
    site = BuildSite(pygame.Rect(80, 80, 40, 40), "eskimo")
    registry.register_build_site(site)
    node_cfg = resource_node_config("ice_shelf", "eskimo")
    node = ResourceNode((40, 0), [], node_cfg, registry)
    drop_cfg = dropoff_config("ice_cutting_post", "eskimo")
    DropoffBuilding((0, 40), [], drop_cfg, registry)

    sim = RtsWorldSim()
    sim.build_controller.registry = registry
    sim.gather_controller.registry = registry
    adapter = FakeWorldAdapter()
    adapter._rts_registry = registry
    sim.assign_build(worker, site, "ice_cutting_post", world_adapter=adapter)
    assert id(worker) in sim.build_controller.tasks

    sim.assign_gather(worker, node, sim.get_wallet("eskimo"))
    assert id(worker) not in sim.build_controller.tasks
    assert id(worker) in sim.gather_controller.tasks
