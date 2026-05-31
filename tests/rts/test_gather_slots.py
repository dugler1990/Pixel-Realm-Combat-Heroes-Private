import pygame

from rts.entities import ResourceNode
from rts.gather_slots import GatherSlotBook, build_gather_slot_positions
from rts.registry import RtsWorldRegistry
from rts.tmx_config import resource_node_config


def test_build_gather_slot_positions_grid():
    slots = build_gather_slot_positions((100, 200), 10, cols=5, spacing=20)
    assert len(slots) == 10
    assert slots[0][0] < slots[4][0]
    assert slots[5][1] > slots[0][1]


def test_gather_slot_book_assigns_unique_goals():
    positions = build_gather_slot_positions((0, 0), 3)
    book = GatherSlotBook(positions)
    workers = [object(), object(), object()]
    goals = [book.claim(w) for w in workers]
    assert len(set(goals)) == 3
    assert book.claim(workers[0]) == goals[0]
    assert not book.has_free()
    book.release(workers[1])
    assert book.has_free()
    assert book.claim(object()) == goals[1]


def test_resource_node_gather_goals_differ_per_worker():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))
    registry = RtsWorldRegistry()
    cfg = resource_node_config("ice_shelf", "eskimo")
    cfg["max_workers"] = 4
    node = ResourceNode((200, 200), [], cfg, registry)
    workers = [object(), object(), object(), object()]
    for worker in workers:
        assert node.register_worker(worker)
    goals = [node.gather_goal_for(w) for w in workers]
    assert len(set(goals)) == 4
