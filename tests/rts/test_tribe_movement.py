import pathlib

import pygame

from QuadTree import QuadTree, QuadTreeManager
from hashRect import HashableRect
from rts.build.states import MOVING_TO_SITE
from rts.entities.gather_states import MOVING_TO_NODE
from rts.entities.worker_entity import RtsWorkerEntity
from rts.combat_context import make_rts_combat_context


def _empty_quad():
    return QuadTree(
        items=[],
        depth=4,
        bounding_rect=pygame.Rect(0, 0, 2000, 2000),
        manager=QuadTreeManager(),
    )


def test_job_driver_moving_sets_status_move():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))
    worker = RtsWorkerEntity(
        (100, 100),
        [],
        "eskimo",
        combat_context=make_rts_combat_context(),
        obstacle_sprites=[],
    )
    worker.gather_state = MOVING_TO_NODE
    worker.move_target = pygame.math.Vector2(200, 100)
    quad = _empty_quad()
    before = pygame.math.Vector2(worker.rect.center)
    worker.update(dt=0.05, QuadTree=quad, entity_quad_tree=quad)
    assert worker.status == "move"
    assert worker.rect.center != tuple(before)


def test_gather_controller_sets_move_target_not_step_toward():
    root = pathlib.Path(__file__).resolve().parents[2]
    gather_src = (root / "Code" / "rts" / "gather" / "controller.py").read_text()
    build_src = (root / "Code" / "rts" / "build" / "controller.py").read_text()
    assert "from navigation.quad_mover import step_toward" not in gather_src
    assert "from navigation.quad_mover import step_toward" not in build_src
    assert "step_toward(" not in gather_src
    assert "step_toward(" not in build_src


def test_build_moving_sets_move_target():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))
    worker = RtsWorkerEntity(
        (50, 50),
        [],
        "eskimo",
        combat_context=make_rts_combat_context(),
        obstacle_sprites=[],
    )
    worker.build_state = MOVING_TO_SITE
    worker.move_target = pygame.math.Vector2(150, 50)
    quad = _empty_quad()
    worker.update(dt=0.05, QuadTree=quad, entity_quad_tree=quad)
    assert worker.status == "move"
