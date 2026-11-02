"""Did an attack touch a body: the one hit test for every attack, client and server.

An attack and a body are each a Shape: a pygame Mask plus the world position of its
top-left pixel. A hit is the two rects overlapping and then the two masks overlapping,
so the mask test only runs for pairs that are already close.

- A sprite's shape is its own hit_shape() when it has one (mesh bosses), else its
  current frame mask at rect.topleft, else its whole rect. A hit_shape() must lie
  inside the sprite's rect.
- A ground blast (meteor, leap slam, ice clone) is a circle on the ground, tested against
  each body's footprint: the ellipse the walls stop (collision_core). ground_reach gives
  the blast's falloff distance on the same circle.
- Candidates are a sprite group, or the entity tree through bodies_near, which turns
  the tree's snapshots back into their entities.

Rect, Mask and plain Surfaces only: no display and no game imports, so it is safe on the
headless server.
"""

import logging
import math

import pygame

import collision_core
from hashRect import HashableRect

# The collision_mask channel in debug_logging.json.
_log = logging.getLogger("game.collision.mask")

_DISCS = {}
_RECT_FALLBACK_LOGGED = set()


class Shape:
    """A mask placed in the world, its top-left pixel at rect.topleft."""

    __slots__ = ("mask", "rect")

    def __init__(self, mask, x, y):
        self.mask = mask
        self.rect = pygame.Rect((int(x), int(y)), mask.get_size())


def rect_shape(rect):
    """A solid rect: the shape of anything without a mask."""
    return Shape(collision_core.solid_mask(rect.width, rect.height), rect.x, rect.y)


def frame_masks(frames):
    """One mask per frame, from its opaque pixels."""
    return [pygame.mask.from_surface(frame) for frame in frames]


def shape_of(sprite):
    """Where this sprite's pixels are right now; None if it has no rect."""
    own = getattr(sprite, "hit_shape", None)
    if own is not None:
        shape = own()
        if shape is not None:
            return shape
    rect = getattr(sprite, "rect", None)
    if rect is None:
        return None
    mask = getattr(sprite, "mask", None)
    if mask is not None:
        if mask.get_size() == rect.size:
            return Shape(mask, rect.x, rect.y)
        kind = type(sprite).__name__
        if kind not in _RECT_FALLBACK_LOGGED:
            # Once per class: a mask that doesn't fit its rect quietly means rect hits.
            _RECT_FALLBACK_LOGGED.add(kind)
            _log.debug(
                "hit shape falls back to the rect: %s mask %s, rect %s",
                kind, mask.get_size(), rect.size,
            )
    return rect_shape(rect)


def _disc_mask(w, h):
    key = (w, h)
    mask = _DISCS.get(key)
    if mask is None:
        surf = pygame.Surface(key, pygame.SRCALPHA)
        pygame.draw.ellipse(surf, (255, 255, 255, 255), surf.get_rect())
        mask = pygame.mask.from_surface(surf)
        _DISCS[key] = mask
    return mask


def ground_disc(center, radius, elevation_deg):
    """A circle of `radius` on the ground around `center`, as the camera sees it.

    The radius is rounded to 2 px so blasts of every size share a few hundred masks.
    """
    r = max(1, int(round(float(radius) / 2.0))) * 2
    w = 2 * r
    h = max(1, int(round(2.0 * r * math.sin(math.radians(float(elevation_deg))))))
    return Shape(_disc_mask(w, h), int(center[0]) - w // 2, int(center[1]) - h // 2)


def foot_shape(sprite):
    """The footprint the walls stop; None for anything without a hitbox and wall_foot."""
    wall_foot = getattr(sprite, "wall_foot", None)
    hitbox = getattr(sprite, "hitbox", None)
    if wall_foot is None or hitbox is None:
        return None
    foot = collision_core.foot_rect(hitbox, wall_foot())
    return Shape(collision_core.foot_mask(foot.width, foot.height), foot.x, foot.y)


def ground_reach(center, foot, elevation_deg):
    """Ground distance from a blast's `center` to the nearest edge of footprint `foot`.

    Screen y is stretched back by 1 / sin(elevation), so a blast's squashed ellipse reads
    as the circle it is on the ground: a footprint touching the ellipse anywhere on its
    edge is about `radius` away. 0 when the centre is inside the footprint.
    """
    s = math.sin(math.radians(float(elevation_deg)))
    fx, fy = foot.rect.center
    dx = fx - center[0]
    dy = (fy - center[1]) / s if s > 0 else fy - center[1]
    return max(0.0, math.hypot(dx, dy) - foot.rect.width / 2.0)


def touching(a, b):
    """True if two shapes share at least one pixel."""
    if a is None or b is None or not a.rect.colliderect(b.rect):
        return False
    return a.mask.overlap(b.mask, (b.rect.x - a.rect.x, b.rect.y - a.rect.y)) is not None


def bodies_near(tree, rect, query_id, margin=32):
    """The entities whose entity-tree entry overlaps `rect` grown by `margin`.

    The tree holds snapshots (HashableRect) from each entity's last move, with the entity
    as `owner`. The margin covers a tick of movement and snapshot rects smaller than the
    sprite (server-side players store their hitbox). Entries without an owner, such as
    projectiles, are skipped, and so is the entry whose id is `query_id` (the attacker).
    """
    if tree is None:
        return []
    area = rect.inflate(2 * margin, 2 * margin)
    owners = []
    for item in tree.hit(HashableRect(area, query_id)):
        owner = getattr(item, "owner", None)
        if owner is not None:
            owners.append(owner)
    return owners


def find_hits(shape, candidates, exclude=(), body=shape_of):
    """Every candidate whose body touches `shape`, each once, in candidate order.

    `body` gives a target's shape: shape_of for swings, projectiles and dashes,
    foot_shape for ground blasts. With shape_of the target's shape lies inside its rect,
    so candidates whose rect misses are dropped first, one cheap test each, and only
    the few close ones reach the loop and the mask test.
    """
    if shape is None:
        return []
    if body is shape_of:
        overlaps = shape.rect.colliderect
        candidates = [
            sprite for sprite in candidates
            if (rect := getattr(sprite, "rect", None)) is not None and overlaps(rect)
        ]
    hits = []
    seen = set()
    for sprite in candidates:
        if sprite in exclude or id(sprite) in seen:
            continue
        seen.add(id(sprite))
        if touching(shape, body(sprite)):
            hits.append(sprite)
    return hits
