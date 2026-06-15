"""Shared obstacle push-out math (display-free, no pygame/game imports).

The rect-based push-out that resolves a moving rect out of overlapping obstacle
rects, factored out of `Entity._resolve_obstacle_collisions` (Code/Entity.py) so
BOTH the client (its rect-collision path) and the headless multiplayer server
call the SAME code -- eliminating the parallel-maintenance duplication the
multiplayer plan's convergence roadmap wanted to remove.

Pure `math`; every function takes rect-likes exposing `left/right/top/bottom/
centerx/centery` (pygame.Rect-compatible), so this module imports nothing heavy
and is safe to use from the server.

The mask (pixel-perfect) path stays in `Entity` -- the server is rect-only by
design (multiplayer plan, Stage B2).
"""

import math

# Base separation distance, matching Entity._resolve_obstacle_collisions'
# `displacement_obstacles = 1`.
DEFAULT_DISPLACEMENT_BASE = 1.0


def rect_penetration(self_rect, obstacle_rect):
    """Penetration "depth" between two rects (Entity.py:421-427, verbatim)."""
    penetration_x = max(
        0, self_rect.right - obstacle_rect.left, obstacle_rect.right - self_rect.left
    )
    penetration_y = max(
        0, self_rect.bottom - obstacle_rect.top, obstacle_rect.bottom - self_rect.top
    )
    return math.sqrt(penetration_x ** 2 + penetration_y ** 2) ** 1.5


def rect_rebound_dir(self_rect, obstacle_rect):
    """Unit rebound direction away from an obstacle's centre (Entity.py:433-439)."""
    collision_normal = math.atan2(
        obstacle_rect.centery - self_rect.centery,
        obstacle_rect.centerx - self_rect.centerx,
    )
    rebound_angle = collision_normal + math.pi
    return math.cos(rebound_angle), math.sin(rebound_angle)


def finalize_pushout(total_dx, total_dy, max_penetration_depth, max_push,
                     displacement_base=DEFAULT_DISPLACEMENT_BASE):
    """Normalize the accumulated rebound and scale it (Entity.py:442-451)."""
    magnitude = math.sqrt(total_dx ** 2 + total_dy ** 2)
    if magnitude > 0:
        total_dx /= magnitude
        total_dy /= magnitude
    scaled = min(displacement_base + max_penetration_depth, max_push)
    return scaled * total_dx, scaled * total_dy


def obstacle_pushout(self_rect, obstacles, max_push,
                     displacement_base=DEFAULT_DISPLACEMENT_BASE):
    """Full rect push-out for `self_rect` against a list of obstacle rects.

    = `finalize_pushout(sum of rect_rebound_dir, max rect_penetration)`. Does NOT
    filter the obstacle list (the caller chooses which obstacles to push against,
    matching how `Entity` already passes whatever its broadphase returned). The
    multiplayer server pre-filters to actually-overlapping obstacles so honest
    players grazing a wall aren't nudged.
    """
    total_dx = 0.0
    total_dy = 0.0
    max_pen = 0.0
    for obstacle_rect in obstacles:
        dx, dy = rect_rebound_dir(self_rect, obstacle_rect)
        total_dx += dx
        total_dy += dy
        pen = rect_penetration(self_rect, obstacle_rect)
        if pen > max_pen:
            max_pen = pen
    return finalize_pushout(total_dx, total_dy, max_pen, max_push, displacement_base)
