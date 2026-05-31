import pygame

from rts.build.controller import BuildController
from rts.build.site import BuildSite
from rts.build.states import MOVING_TO_SITE
from rts.entities import RtsWorker


def test_build_move_along_path_does_not_finish_at_first_waypoint():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    site = BuildSite(pygame.Rect(2400, 2700, 50, 50), "eskimo", requires="deep_snow")
    final = site.build_center
    worker = RtsWorker((2257, 3366), [], "eskimo", "worker_eskimo")
    worker.assigned_build_site = site
    worker.build_state = MOVING_TO_SITE
    worker._build_path = [
        pygame.math.Vector2(2325, 3375),
        pygame.math.Vector2(2400, 2800),
        pygame.math.Vector2(final[0], final[1]),
    ]
    worker._build_path_index = 0
    worker.rect.center = (2325, 3375)

    ctrl = BuildController()
    arrived = ctrl._move_along_path(worker, final, 0.05, None)

    assert not arrived
    assert worker._build_path_index == 1
    assert worker.build_state == MOVING_TO_SITE


def test_build_move_along_path_finishes_at_final_goal():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))

    site = BuildSite(pygame.Rect(2400, 2700, 50, 50), "eskimo", requires="deep_snow")
    final = site.build_center
    worker = RtsWorker(final, [], "eskimo", "worker_eskimo")
    worker.assigned_build_site = site
    worker.build_state = MOVING_TO_SITE
    worker._build_path = [pygame.math.Vector2(final[0], final[1])]
    worker._build_path_index = 0
    worker.rect.center = final

    ctrl = BuildController()
    arrived = ctrl._move_along_path(worker, final, 0.05, None)

    assert arrived
