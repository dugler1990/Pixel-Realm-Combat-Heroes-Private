import math

import pygame

from hashRect import HashableRect

_REACH_RADIUS = 14.0


def step_toward(unit_rect, target, dt, speed, obstacle_quad_tree, skip_sprites=None, reach=None):
    """Move unit_rect toward target with quad-tree obstacle sliding.

    Returns True when within reach distance of target.
    """
    reach = _REACH_RADIUS if reach is None else float(reach)
    pos = pygame.math.Vector2(unit_rect.center)
    goal = pygame.math.Vector2(target)
    delta = goal - pos
    dist = delta.length()
    step = float(speed) * float(dt or 0)

    if dist <= max(reach, step):
        return True

    if step <= 0 or dist <= 0:
        return False

    move = delta.normalize() * min(step, dist)
    unit_rect.centerx += int(move.x)
    unit_rect.centery += int(move.y)

    if obstacle_quad_tree is not None:
        _resolve_obstacle_slide(
            unit_rect,
            obstacle_quad_tree,
            skip_sprites,
            max(step, 1.0),
        )

    return pygame.math.Vector2(unit_rect.center).distance_to(goal) <= reach


def _resolve_obstacle_slide(unit_rect, obstacle_quad_tree, skip_sprites, speed):
    query = HashableRect(unit_rect.copy())
    nearby = obstacle_quad_tree.hit(query)
    if not nearby:
        return

    skip = skip_sprites or ()
    total_dx = 0.0
    total_dy = 0.0
    max_penetration = 0.0

    for obstacle in nearby:
        if _should_skip(obstacle, skip):
            continue
        obstacle_rect = obstacle.rect
        if not unit_rect.colliderect(obstacle_rect):
            continue

        collision_normal = math.atan2(
            obstacle_rect.centery - unit_rect.centery,
            obstacle_rect.centerx - unit_rect.centerx,
        )
        rebound_angle = collision_normal + math.pi

        penetration_x = max(
            0,
            unit_rect.right - obstacle_rect.left,
            obstacle_rect.right - unit_rect.left,
        )
        penetration_y = max(
            0,
            unit_rect.bottom - obstacle_rect.top,
            obstacle_rect.bottom - unit_rect.top,
        )
        penetration_depth = math.sqrt(penetration_x ** 2 + penetration_y ** 2) ** 1.5

        total_dx += math.cos(rebound_angle)
        total_dy += math.sin(rebound_angle)
        max_penetration = max(max_penetration, penetration_depth)

    magnitude = math.hypot(total_dx, total_dy)
    if magnitude <= 0:
        return

    total_dx /= magnitude
    total_dy /= magnitude
    scaled = min(1.0 + max_penetration, speed)
    unit_rect.left += int(scaled * total_dx)
    unit_rect.top += int(scaled * total_dy)


def _should_skip(obstacle_item, skip_sprites):
    obstacle_rect = getattr(obstacle_item, "rect", None)
    if obstacle_rect is None:
        return False
    for sprite in skip_sprites:
        if sprite is None:
            continue
        sprite_rect = getattr(sprite, "rect", None)
        if sprite_rect is None:
            continue
        if obstacle_rect.colliderect(sprite_rect):
            return True
    return False
