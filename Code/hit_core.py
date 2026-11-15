"""Did an attack touch a body: the one hit test for every attack, client and server.

An attack and a body are each a Shape: a pygame Mask plus the world position of its
top-left pixel. A hit is the two rects overlapping and then the two masks overlapping,
so the mask test only runs for pairs that are already close.

- A sprite's shape is its own hit_shape() when it has one (mesh bosses, the mesh hero),
  else its current frame mask at rect.topleft, else its whole rect. A hit_shape() must
  lie inside the sprite's rect, or the sprite is listed with reaches_past_rect and its
  hit_rect holds it (the mesh hero: a foot stepping toward the camera is below his
  sprite).
- A ground blast (meteor, leap slam, ice clone) is a circle on the ground, tested against
  each body's footprint: the ellipse the walls stop (collision_core). ground_reach gives
  the blast's falloff distance on the same circle.
- Candidates are a sprite group, or the entity tree through bodies_near, which turns
  the tree's snapshots back into their entities.
- A contact is the world pixel where a hit landed (touch_point, find_contacts); a moving
  shot's contact is walked back to where it entered the body (entry_point).

Rect, Mask and plain Surfaces only: no display and no game imports, so it is safe on the
headless server.
"""

import logging
import math
import weakref

import pygame

import collision_core
from hashRect import HashableRect

# The collision_mask channel in debug_logging.json.
_log = logging.getLogger("game.collision.mask")

_DISCS = {}
_RECT_FALLBACK_LOGGED = set()
# Bodies whose hit_shape reaches past their rect: checked by their hit_rect after the rect test,
# so the rect test itself costs every other candidate nothing more.
_REACHING = weakref.WeakSet()


def reaches_past_rect(sprite):
    """List a body whose hit_shape can lie outside its rect; its hit_rect (None: use rect) must
    hold the shape."""
    _REACHING.add(sprite)


class Shape:
    """A mask placed in the world, its top-left pixel at rect.topleft.

    `solid` marks a plain rect (rect_shape): every pixel set, so its first shared pixel
    with another solid shape is just a corner of the overlap.
    """

    __slots__ = ("mask", "rect", "solid")

    def __init__(self, mask, x, y, solid=False):
        self.mask = mask
        self.rect = pygame.Rect((int(x), int(y)), mask.get_size())
        self.solid = solid


def rect_shape(rect):
    """A solid rect: the shape of anything without a mask."""
    return Shape(collision_core.solid_mask(rect.width, rect.height), rect.x, rect.y, solid=True)


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


def touch_point(a, b):
    """The world (x, y) of a pixel two shapes share, or None if they share none.

    The pixel is the first one pygame's overlap scan finds (left-most bit-column band
    first), not where an attack arrived. Two solid shapes give the centre of their rect
    overlap instead: their first shared pixel is only its top-left corner.
    """
    if a is None or b is None or not a.rect.colliderect(b.rect):
        return None
    ax, ay = a.rect.topleft
    hit = a.mask.overlap(b.mask, (b.rect.x - ax, b.rect.y - ay))
    if hit is None:
        return None
    if a.solid and b.solid:
        return a.rect.clip(b.rect).center
    return (ax + hit[0], ay + hit[1])


def touching(a, b):
    """True if two shapes share at least one pixel."""
    if a is None or b is None or not a.rect.colliderect(b.rect):
        return False
    return a.mask.overlap(b.mask, (b.rect.x - a.rect.x, b.rect.y - a.rect.y)) is not None


def entry_point(point, step, body, max_steps=64):
    """Where a shot moving by `step` entered `body`, walking back from `point` inside it.

    `point` is a body pixel the shot touches (touch_point); the shot came along `step`, so
    the line back through `point` leaves the body where the shot crossed its outline. The
    walk reads at most `max_steps` pixels (capped at 64) and returns the last body pixel on
    it. A zero step, or a `point` not on the body, is returned as is.
    """
    sx, sy = float(step[0]), float(step[1])
    length = math.hypot(sx, sy)
    if length == 0.0 or body is None:
        return point
    sx, sy = sx / length, sy / length
    rx, ry = body.rect.topleft
    w, h = body.rect.size
    get_at = body.mask.get_at
    px, py = point[0] - rx, point[1] - ry
    if not (0 <= px < w and 0 <= py < h) or not get_at((px, py)):
        return point
    last = (px, py)
    for i in range(1, min(int(max_steps), 64) + 1):
        x = int(round(px - sx * i))
        y = int(round(py - sy * i))
        if not (0 <= x < w and 0 <= y < h) or not get_at((x, y)):
            break
        last = (x, y)
    return (rx + last[0], ry + last[1])


class EntryPoints:
    """A moving shot's contacts by target id, each walked back (entry_point) only when asked.

    Built from find_contacts. The walk costs ~20 us, so it runs only for the hits that
    land: InteractionResolver.strike asks after its repeat and team checks.
    """

    __slots__ = ("_found", "_step", "_reach")

    def __init__(self, found, step, reach):
        self._found = {id(sprite): (point, body_shape) for sprite, point, body_shape in found}
        self._step = step
        self._reach = reach

    def get(self, key, default=None):
        hit = self._found.get(key)
        if hit is None:
            return default
        return entry_point(hit[0], self._step, hit[1], self._reach)


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


def _close(shape, candidates, body):
    """With shape_of bodies, only the candidates whose rect overlaps `shape`, then any listed
    body (reaches_past_rect) whose hit_rect does though its rect missed: that one comes last."""
    if body is not shape_of:
        return candidates
    overlaps = shape.rect.colliderect
    close = [
        sprite for sprite in candidates
        if (rect := getattr(sprite, "rect", None)) is not None and overlaps(rect)
    ]
    for sprite in _REACHING:
        hit_rect = sprite.hit_rect
        if (hit_rect is not None and overlaps(hit_rect) and sprite not in close
                and sprite in candidates):
            close.append(sprite)
    return close


def find_hits(shape, candidates, exclude=(), body=shape_of):
    """Every candidate whose body touches `shape`, each once, in candidate order.

    `body` gives a target's shape: shape_of for swings, projectiles and dashes,
    foot_shape for ground blasts. With shape_of the target's shape lies inside its rect,
    so candidates whose rect misses are dropped first, one cheap test each, and only
    the few close ones reach the loop and the mask test.
    """
    if shape is None:
        return []
    hits = []
    seen = set()
    for sprite in _close(shape, candidates, body):
        if sprite in exclude or id(sprite) in seen:
            continue
        seen.add(id(sprite))
        if touching(shape, body(sprite)):
            hits.append(sprite)
    return hits


def find_contacts(shape, candidates, exclude=(), body=shape_of):
    """find_hits, with where each hit landed: [(sprite, point, body_shape), ...].

    Same bodies in the same order as find_hits. `point` is touch_point's world pixel;
    `body_shape` is the target's shape, for entry_point without asking for it again.
    """
    if shape is None:
        return []
    contacts = []
    seen = set()
    for sprite in _close(shape, candidates, body):
        if sprite in exclude or id(sprite) in seen:
            continue
        seen.add(id(sprite))
        target_shape = body(sprite)
        point = touch_point(shape, target_shape)
        if point is not None:
            contacts.append((sprite, point, target_shape))
    return contacts
