import pygame

from rts.categories import FOOD
from rts.entities import DropoffBuilding, ResourceNode, RtsWorker
from rts.entities.worker import DELIVERING
from rts.registry import RtsWorldRegistry
from rts.resources import ResourceWallet
from rts.tmx_config import dropoff_config, resource_node_config
from rts.world_sim import RtsWorldSim

from fakes import FakeWorldAdapter


def test_exit_preserves_gather_tasks_via_world_sim():
    world = FakeWorldAdapter()
    world_sim = RtsWorldSim()
    worker = RtsWorker((0, 0), [], "eskimo_tribe", "worker_eskimo")
    world_sim.gather_controller.tasks[id(worker)] = worker
    world_sim.tick(0.016, world)
    assert id(worker) in world_sim.gather_controller.tasks


def test_world_sim_tick_advances_gather_while_session_inactive():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    registry = RtsWorldRegistry()
    worker = RtsWorker((0, 0), [], "eskimo_tribe", "worker_eskimo")
    node_cfg = resource_node_config("fruit_grove", "eskimo_tribe")
    node_cfg["gather_duration"] = 0.05
    node = ResourceNode((30, 0), [], node_cfg, registry)
    drop_cfg = dropoff_config("village_hearth", "eskimo_tribe")
    dropoff = DropoffBuilding((0, 30), [], drop_cfg, registry)

    world_sim = RtsWorldSim()
    wallet = world_sim.get_wallet("eskimo_tribe")
    world_sim.gather_controller.registry = registry
    world_sim.gather_controller.assign(worker, node, wallet)
    worker.rect.center = node.gather_point

    world = FakeWorldAdapter()
    world._rts_registry = registry

    initial = worker.gather_state
    for _ in range(80):
        world_sim.tick(0.05, world)

    assert worker.gather_state != initial or wallet.get(node.resource_category) > 0


def test_wallet_persists_across_session_enter():
    world_sim = RtsWorldSim()
    wallet = world_sim.get_wallet("eskimo_tribe")
    wallet.add(FOOD, 7)
    wallet2 = world_sim.get_wallet("eskimo_tribe")
    assert wallet2.get(FOOD) == 7
    assert wallet is wallet2


def test_deliver_uses_faction_wallet_resolver():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    registry = RtsWorldRegistry()
    worker = RtsWorker((0, 0), [], "eskimo_tribe", "worker_eskimo")
    node_cfg = resource_node_config("fruit_grove", "eskimo_tribe")
    node_cfg["gather_duration"] = 0.01
    node = ResourceNode((0, 0), [], node_cfg, registry)
    drop_cfg = dropoff_config("village_hearth", "eskimo_tribe")
    DropoffBuilding((0, 0), [], drop_cfg, registry)

    sim = RtsWorldSim()
    sim.gather_controller.registry = registry
    eskimo_wallet = sim.get_wallet("eskimo_tribe")
    jungle_wallet = sim.get_wallet("jungle_tribe")

    controller = sim.gather_controller
    controller.assign(worker, node, None)
    worker.gather_state = DELIVERING
    worker._timer = 0.0
    worker._delivery_category = node.resource_category
    worker._delivery_amount = node.yield_amount
    worker.assigned_dropoff = registry.find_dropoff("eskimo_tribe", node.dropoff_kind)
    controller.tasks[id(worker)] = worker
    controller.update(0.1, None)

    assert eskimo_wallet.get(node.resource_category) > 0
    assert jungle_wallet.get(node.resource_category) == 0
