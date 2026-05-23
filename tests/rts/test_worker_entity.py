import pygame

from Interaction import InteractionContext, InteractionResolver
from rts.entities.worker_entity import RtsWorkerEntity
from rts.gather.controller import GatherController
from rts.registry import RtsWorldRegistry
from rts.world_sim import RtsWorldSim


def test_worker_damage_cancels_gather_and_unregisters():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    registry = RtsWorldRegistry()
    sim = RtsWorldSim()
    sim.gather_controller.registry = registry
    worker = RtsWorkerEntity((50, 50), [], "eskimo_tribe", world_sim=sim, health=1)
    registry.register_worker(worker)
    sim.gather_controller.tasks[id(worker)] = worker

    ctx = InteractionContext(
        kind="damage",
        source_kind="enemy",
        source_team="enemy_1",
        target=worker,
        amount=5,
        attack_type="weapon",
    )
    worker.receive_interaction(ctx)

    assert worker not in registry.workers_by_faction.get("eskimo_tribe", [])
    assert id(worker) not in sim.gather_controller.tasks


def test_enemy_can_aggro_neutral_passive_worker():
    resolver = InteractionResolver()
    enemy = type("E", (), {"team_id": "enemy_1"})()
    worker = type("W", (), {"team_id": "neutral_passive"})()
    assert resolver.can_aggro(enemy, worker)
