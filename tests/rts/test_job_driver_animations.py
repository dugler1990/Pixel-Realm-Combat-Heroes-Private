import pygame

from rts.behavior_drivers import JobDriver, WALK_STATUSES
from rts.build.states import BUILDING, CLEARING_SNOW, MOVING_TO_SITE
from rts.entities.gather_states import (
    DELIVERING,
    GATHERING,
    MOVING_TO_DROPOFF,
    MOVING_TO_NODE,
)


class _StubUnit:
    def __init__(self, gather_state=None, build_state="BUILD_IDLE", move_target=None):
        self.gather_state = gather_state
        self.build_state = build_state
        self.move_target = move_target
        self.status = "idle"
        self.direction = pygame.math.Vector2(0, 0)
        self.direction_string = "right"
        self.rect = pygame.Rect(0, 0, 32, 32)

    def steer_toward(self, point):
        self.direction = pygame.math.Vector2(1, 0)
        self.status = "move"


def test_walk_statuses_include_haul_ice():
    assert "haul_ice" in WALK_STATUSES


def test_job_driver_maps_gather_and_build_and_haul():
    driver = JobDriver()
    ctx = type("Ctx", (), {"dt": 0.0, "entity_quad_tree": None, "obstacle_sprites": None})()

    u = _StubUnit(gather_state=GATHERING)
    driver.steer(u, 0, ctx)
    assert u.status == "gather"

    u = _StubUnit(build_state=BUILDING)
    driver.steer(u, 0, ctx)
    assert u.status == "build"

    u = _StubUnit(build_state=CLEARING_SNOW)
    driver.steer(u, 0, ctx)
    assert u.status == "build"

    u = _StubUnit(gather_state=MOVING_TO_DROPOFF, move_target=(100, 100))
    driver.steer(u, 0, ctx)
    assert u.status == "haul_ice"

    u = _StubUnit(gather_state=MOVING_TO_NODE, move_target=(100, 100))
    driver.steer(u, 0, ctx)
    assert u.status == "move"

    u = _StubUnit(build_state=MOVING_TO_SITE, move_target=(100, 100))
    driver.steer(u, 0, ctx)
    assert u.status == "move"

    u = _StubUnit(gather_state=DELIVERING)
    driver.steer(u, 0, ctx)
    assert u.status == "idle"
