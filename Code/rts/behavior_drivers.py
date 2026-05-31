import math
import random
import time

import pygame

from game_logging import get_debug_logger

from .build.states import BUILDING, BUILD_IDLE, CLEARING_SNOW, MOVING_TO_SITE
from .entities.gather_states import (
    DELIVERING,
    GATHERING,
    MOVING_TO_DROPOFF,
    MOVING_TO_NODE,
    WAITING_AT_NODE,
)

WALK_STATUSES = ("move", "haul_ice")

_GATHER_MOVING = {MOVING_TO_NODE, MOVING_TO_DROPOFF}
_BUILD_MOVING = {MOVING_TO_SITE}

_rts_log = get_debug_logger("rts")
_STUCK_MOVE_TARGET_LOG_INTERVAL = 2.0


class DriverContext:
    def __init__(self, entity_quad_tree=None, obstacle_sprites=None, dt=0.0):
        self.entity_quad_tree = entity_quad_tree
        self.obstacle_sprites = obstacle_sprites
        self.dt = float(dt or 0)


class JobDriver:
    def __init__(self):
        self._missing_move_target_next = {}

    def _walk_status(self, gather_state, build_state):
        if gather_state == MOVING_TO_DROPOFF:
            return "haul_ice"
        if gather_state == MOVING_TO_NODE or build_state in _BUILD_MOVING:
            return "move"
        return "idle"

    def steer(self, unit, dt, ctx):
        gather_state = getattr(unit, "gather_state", None)
        build_state = getattr(unit, "build_state", BUILD_IDLE)
        move_target = getattr(unit, "move_target", None)

        if gather_state in _GATHER_MOVING or build_state in _BUILD_MOVING:
            if move_target is not None:
                unit.steer_toward(move_target)
                unit.status = self._walk_status(gather_state, build_state)
            else:
                if build_state in _BUILD_MOVING:
                    wid = id(unit)
                    now = time.monotonic()
                    if now >= self._missing_move_target_next.get(wid, 0.0):
                        self._missing_move_target_next[wid] = (
                            now + _STUCK_MOVE_TARGET_LOG_INTERVAL
                        )
                        _rts_log.warning(
                            "job driver: build MOVING_TO_SITE but no move_target worker@%s",
                            getattr(unit, "rect", None) and unit.rect.center,
                        )
                unit.status = "idle"
                unit.direction = pygame.math.Vector2(0, 0)
            return

        if gather_state == GATHERING:
            unit.status = "gather"
            unit.direction = pygame.math.Vector2(0, 0)
            return

        if build_state in (CLEARING_SNOW, BUILDING):
            unit.status = "build"
            unit.direction = pygame.math.Vector2(0, 0)
            return

        if gather_state == WAITING_AT_NODE or gather_state == DELIVERING:
            unit.status = "idle"
            unit.direction = pygame.math.Vector2(0, 0)
            return

        unit.status = "idle"
        unit.direction = pygame.math.Vector2(0, 0)


class CombatDriver:
    def steer(self, unit, dt, ctx):
        if getattr(unit, "frozen", False):
            return
        target = unit.select_hostile_target()
        if target is None:
            unit.status = "idle"
            unit.direction = pygame.math.Vector2(0, 0)
            return
        unit.actions(target, ctx.entity_quad_tree)


class RoamDriver:
    def steer(self, unit, dt, ctx):
        if getattr(unit, "interacting", False):
            unit.status = "idle"
            unit.direction = pygame.math.Vector2(0, 0)
            unit.move_target = None
            return

        wait = float(getattr(unit, "_roam_wait_timer", 0.0)) - float(dt or 0)
        unit._roam_wait_timer = wait
        target = getattr(unit, "_roam_target", None)
        if target is None or wait <= 0:
            unit._pick_roam_target()
            unit._roam_wait_timer = random.uniform(2.0, 4.0)
            target = unit._roam_target

        if target is None:
            unit.status = "idle"
            unit.direction = pygame.math.Vector2(0, 0)
            return

        goal = pygame.math.Vector2(target)
        pos = pygame.math.Vector2(unit.rect.center)
        reach = max(4.0, float(getattr(unit, "speed", 4)) * float(dt or 0))
        if pos.distance_to(goal) <= reach:
            unit._roam_target = None
            unit.status = "idle"
            unit.direction = pygame.math.Vector2(0, 0)
            return

        unit.steer_toward(goal)


_DRIVERS = {
    "job": JobDriver(),
    "combat": CombatDriver(),
    "roam": RoamDriver(),
}


def pick_driver(behavior):
    return _DRIVERS.get(str(behavior or "job"), _DRIVERS["job"])
