"""Walls block the feet: the one wall-collision path for the client and the server.

`Entity` (the client, and the enemies in the server's own `Level4`) and the server's
check on each reported player position call these same functions on the same obstacle
quad-tree, so an honest client is never corrected.

The body is a footprint: a ground circle of radius R at the drawn feet, seen as an
ellipse 2R wide and 2R * sin(view elevation) tall. Walls are the obstacle quad-tree's
items as they are: a rect plus a pygame mask, where mask None means the whole rect is
solid. Every test is an integer mask overlap, so client and server agree to the pixel.

Rect and Mask only: no display, no surfaces, no game imports, so it is safe on the
headless server.
"""

import math

import pygame

from hashRect import HashableRect

# QuadTree.hit skips items whose _id equals the query's, and every static obstacle
# carries -1, so the query needs an id that nothing in the tree uses.
_QUERY_ID = -999_999

# When the straight step is blocked on both axes, try the whole step turned by these
# angles, smallest first, to each side; each try is shortened by cos(angle). One 45°
# try only slides on walls within 45° of the push, and with the 45° camera a wall at
# 45° on the ground draws at about 35° on screen, so a single try would stick there.
SLIDE_ANGLES_DEG = (15, 30, 45, 60, 75)

# When even the turned tries are blocked, sidestep up to this many pixels across the push if
# that then lets the step make one pixel of progress. SAM's wall edges have small 3-4 px
# near-vertical jogs that act like tiny flat walls under the feet. A flat wall never allows
# progress after a sidestep, so pushing square into one still stops you dead.
SIDESTEP_PX = 4

_FOOT_MASKS = {}
_SOLID_MASKS = {}


def wall_foot_for(hitbox_size, feet_offset_y, radius, elevation_deg):
    """The footprint as (dx, dy, w, h) relative to the hitbox's topleft.

    Centred on the drawn feet: hitbox.midbottom shifted down by `feet_offset_y`.
    """
    hw, hh = int(hitbox_size[0]), int(hitbox_size[1])
    r = max(1.0, float(radius))
    w = max(1, int(round(2.0 * r)))
    h = max(1, int(round(2.0 * r * math.sin(math.radians(float(elevation_deg))))))
    feet_x = hw // 2  # pygame's midbottom x for a rect at x=0
    feet_y = hh + int(feet_offset_y)
    return (feet_x - w // 2, feet_y - h // 2, w, h)


def foot_rect(hitbox, wall_foot):
    """The footprint's rect in world pixels for a hitbox."""
    dx, dy, w, h = wall_foot
    return pygame.Rect(hitbox.x + dx, hitbox.y + dy, w, h)


def foot_mask(w, h):
    """The footprint ellipse as a Mask, cached per size."""
    key = (int(w), int(h))
    mask = _FOOT_MASKS.get(key)
    if mask is None:
        w, h = key
        mask = pygame.Mask((w, h))
        rx, ry = w / 2.0, h / 2.0
        for y in range(h):
            ny = (y + 0.5 - ry) / ry
            for x in range(w):
                nx = (x + 0.5 - rx) / rx
                if nx * nx + ny * ny <= 1.0:
                    mask.set_at((x, y), 1)
        _FOOT_MASKS[key] = mask
    return mask


def hitbox_from_center(center, size):
    """The client's hitbox from its reported centre.

    `Rect.center = c` sets x = c - w // 2, the exact inverse of how `.center` was read.
    """
    rect = pygame.Rect((0, 0), (int(size[0]), int(size[1])))
    rect.center = (int(round(center[0])), int(round(center[1])))
    return rect


def _solid_mask(w, h):
    key = (int(w), int(h))
    mask = _SOLID_MASKS.get(key)
    if mask is None:
        mask = pygame.Mask(key, fill=True)
        _SOLID_MASKS[key] = mask
    return mask


def _nearby(tree, area):
    if tree is None:
        return []
    return list(tree.hit(HashableRect(area, _id=_QUERY_ID)))


def _overlaps(foot, fmask, items):
    for item in items:
        rect = item.rect
        if not foot.colliderect(rect):
            continue
        mask = getattr(item, "mask", None)
        if mask is None:
            mask = _solid_mask(rect.width, rect.height)
        if mask.overlap(fmask, (foot.x - rect.x, foot.y - rect.y)):
            return True
    return False


def hits_wall(foot, tree):
    """True if the footprint at `foot` overlaps any wall's solid pixels."""
    items = _nearby(tree, foot)
    if not items:
        return False
    return _overlaps(foot, foot_mask(foot.width, foot.height), items)


def walls_version(tree):
    """A number that changes whenever a wall is inserted into, removed from or reshaped in `tree`."""
    return getattr(getattr(tree, "manager", None), "version", 0)


def _advance(clear, d, along_x, base):
    """How far, up to the integer `d`, a move along one axis gets before first contact."""
    if d == 0:
        return 0
    s = 1 if d > 0 else -1
    bx, by = base
    reached = 0
    for i in range(1, abs(d) + 1):
        ox, oy = (bx + s * i, by) if along_x else (bx, by + s * i)
        if not clear(ox, oy):
            break
        reached = s * i
    return reached


def blocked_step(foot, dx, dy, tree):
    """The integer step (dx, dy) the footprint actually takes against the walls.

    - x as far as it can go before touching a wall, then y, to the pixel;
    - if neither moved, the whole step turned by SLIDE_ANGLES_DEG to each side,
      smallest turn first, each shortened by cos(angle), as one diagonal move: the
      first that's clear and still moves along the push wins, so pushing into a wall
      at any angle slides along it, and pushing square into a flat wall stops;
    - if those are blocked too, a sidestep of up to SIDESTEP_PX across the push plus one
      pixel forward, smallest first, so small jogs in SAM's edges don't snag;
    - a footprint that already overlaps a wall moves freely until it's clear, so
      nothing that spawns or lands inside a wall gets stuck.
    """
    dx, dy = int(dx), int(dy)
    if tree is None or (dx == 0 and dy == 0):
        return dx, dy
    reach = abs(dx) + abs(dy) + SIDESTEP_PX
    items = _nearby(tree, foot.inflate(2 * reach + 2, 2 * reach + 2))
    if not items:
        return dx, dy
    fmask = foot_mask(foot.width, foot.height)

    def clear(ox, oy):
        return not _overlaps(foot.move(ox, oy), fmask, items)

    if not clear(0, 0):
        return dx, dy

    tx = _advance(clear, dx, True, (0, 0))
    ty = _advance(clear, dy, False, (tx, 0))
    if tx or ty:
        return tx, ty

    length = math.hypot(dx, dy)
    heading = math.atan2(dy, dx)
    for deg in SLIDE_ANGLES_DEG:
        turn = math.radians(deg)
        scale = length * math.cos(turn)
        for sign in (1, -1):
            angle = heading + sign * turn
            ox = int(round(scale * math.cos(angle)))
            oy = int(round(scale * math.sin(angle)))
            # Rounding can turn a small try square to the push; that would drift you
            # along a flat wall you push straight into, so it must still move forward.
            if ox * dx + oy * dy <= 0:
                continue
            if clear(ox, oy):
                return ox, oy

    if abs(dx) >= abs(dy):
        forward, across = (1 if dx > 0 else -1, 0), (0, 1)
    else:
        forward, across = (0, 1 if dy > 0 else -1), (1, 0)
    # How far each side is clear, found once rather than again for every width.
    room = {}
    for sign in (1, -1):
        room[sign] = 0
        for i in range(1, SIDESTEP_PX + 1):
            if not clear(across[0] * sign * i, across[1] * sign * i):
                break
            room[sign] = i
    for n in range(1, SIDESTEP_PX + 1):
        for sign in (1, -1):
            if n > room[sign]:
                continue
            ox = across[0] * sign * n + forward[0]
            oy = across[1] * sign * n + forward[1]
            if clear(ox, oy):
                return ox, oy
    return 0, 0
