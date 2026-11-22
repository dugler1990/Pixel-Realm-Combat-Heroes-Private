"""Arrows that stay where they hit (damage chunk 11, docs/damage/PLAN_stuck_arrows.md).

Only a body with `keeps_arrows` (the player) keeps them, and only on his mesh points. An arrow keeps
when it landed and went in: it reached flesh, or it stopped in a layer that `catches` (plate does
not: it glances). Each is the mesh point it hit, its travel turned into the body's own frame, and how
much of the shaft shows. Every frame it is placed from the posed points (the animation) and the
current yaw, and drawn only when that point is in front. At most STUCK_MAX, each for STUCK_MS;
death or a change of what he wears drops them.
"""
import math

import pygame

from damage_rules import STUCK_MAX, STUCK_MS
from Settings import VIEW_ELEVATION_DEG

SHAFT_PX = 22          # a whole arrow on screen
FLESH_SHOWS = 0.5      # share of the shaft outside when it reached flesh
LAYER_SHOWS = 0.8      # when it stuck in an outer layer
FRONT_TOL = 3.0        # px of depth a point may sit behind the front one and still be seen
_ANGLES = 32
_SHAFT = (110, 80, 50, 255)
_FLETCH = (235, 235, 225, 255)


class Stuck:
    __slots__ = ("point", "angle", "shows", "until_ms")

    def __init__(self, point, angle, shows, until_ms):
        self.point = point            # index into the worn point cloud
        self.angle = angle            # travel, radians, in the body's own frame
        self.shows = shows
        self.until_ms = until_ms


def caught(priced):
    """Did the arrow go in: flesh, or a layer that catches."""
    if getattr(priced, "reached_flesh", False):
        return True
    layer = getattr(priced, "stopped_at", None)
    return layer is not None and getattr(layer, "catches", True)


def keep(ctx, priced, now):
    """After a landed hit: keep the arrow when the body keeps arrows and it went in."""
    target = ctx.target
    attack = ctx.attack_def
    if (not getattr(target, "keeps_arrows", False) or attack is None or attack.delivery != "pierce"
            or not attack.stops or ctx.contact is None or not caught(priced)):
        return
    import body_regions
    from hit_resolve import _toward
    toward = _toward(ctx)
    spot = body_regions.hit_layers(target, ctx.contact, toward)
    skin = target.mesh_skin
    if spot.point is None or skin is None or toward is None:
        return
    travel = math.atan2(toward[1], toward[0])
    add(target, int(spot.point), travel - math.radians(skin.yaw_deg()),
        FLESH_SHOWS if getattr(priced, "reached_flesh", False) else LAYER_SHOWS, now)


def add(body, point, angle, shows, now):
    arrows = _arrows(body)
    arrows.append(Stuck(point, angle, shows, now + STUCK_MS))
    if len(arrows) > STUCK_MAX:
        del arrows[0]


def forget(body):
    if getattr(body, "stuck_arrows", None):
        body.stuck_arrows = []


def placed(body, now):
    """(tip, angle on screen, shows) per arrow to draw now, the tip in world pixels. Expired ones
    go; a change of worn pieces drops all (the point indices belong to the old cloud)."""
    arrows = getattr(body, "stuck_arrows", None)
    if not arrows:
        return []
    arrows[:] = [a for a in arrows if a.until_ms > now]
    skin = body._drawn_skin() if hasattr(body, "_drawn_skin") else None
    if skin is None or not arrows:
        return []
    pieces = tuple(skin.pieces)
    if getattr(body, "_stuck_pieces", pieces) != pieces:
        arrows.clear()
    body._stuck_pieces = pieces
    if not arrows:
        return []
    found = body.hit_outline()
    if found is None:
        return []
    outline, feet = found
    points = body._worn_cloud(skin).posed(skin.skin.frame_index)
    yaw = math.radians(skin.yaw_deg())
    scale = body._mesh_scale(skin)
    out = []
    for a in arrows:
        if a.point >= len(points):
            continue
        sx, sy, depth = project(points[a.point], yaw, scale)
        if not _in_front(outline, points, sx, sy, depth, yaw, scale):
            continue
        out.append(((feet[0] + sx, feet[1] + sy), a.angle + yaw, a.shows))
    return out


def project(p, yaw, scale, elevation_deg=VIEW_ELEVATION_DEG):
    """A posed point to (screen x, screen y from the feet, depth): mesh_points' own projection."""
    c, s = math.cos(yaw), math.sin(yaw)
    e = math.radians(elevation_deg)
    gy = -(p[0] * s + p[1] * c) * scale
    gz = p[2] * scale
    return (math.floor((p[0] * c - p[1] * s) * scale), math.floor(gy * math.sin(e) - gz * math.cos(e)),
            gy * math.cos(e) + gz * math.sin(e))


def draw(camera, body, now):
    """The camera's pass: each arrow as a shaft from its tip back along where it came from."""
    for (tx, ty), angle, shows in placed(body, now):
        length = int(SHAFT_PX * shows)
        surf, half = _shaft(round(angle / (2 * math.pi) * _ANGLES) % _ANGLES, length)
        camera.backend.blit(surf, (tx - camera.offset.x - half, ty - camera.offset.y - half),
                            cache_key=id(surf))


# --- inside -----------------------------------------------------------------------------------

def _arrows(body):
    arrows = getattr(body, "stuck_arrows", None)
    if arrows is None:
        arrows = []
        body.stuck_arrows = arrows
    return arrows


def _in_front(outline, points, sx, sy, depth, yaw, scale):
    """The point drawn in front at the arrow's pixel is no nearer than the arrow's own (within FRONT_TOL)."""
    h, w = outline.labels.shape
    x, y = int(sx - outline.dx), int(sy - outline.dy)
    if not (0 <= x < w and 0 <= y < h):
        return False
    front = int(outline.labels[y, x])
    if front < 0:
        return True
    return depth >= project(points[front], yaw, scale)[2] - FRONT_TOL


_SHAFTS = {}


def _shaft(bucket, length):
    """A cached square surface with the tip at its centre and the shaft pointing back."""
    key = (bucket, length)
    found = _SHAFTS.get(key)
    if found is None:
        half = length + 2
        surf = pygame.Surface((2 * half, 2 * half), pygame.SRCALPHA)
        back = bucket / _ANGLES * 2 * math.pi + math.pi          # from the tip toward the shooter
        dx, dy = math.cos(back), math.sin(back)
        tail = (half + dx * length, half + dy * length)
        pygame.draw.line(surf, _SHAFT, (half, half), tail, 2)
        pygame.draw.line(surf, _FLETCH, (half + dx * (length - 5), half + dy * (length - 5)), tail, 3)
        found = (surf, half)
        _SHAFTS[key] = found
    return found
