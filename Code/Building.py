"""Authored building interiors: one region, two surfaces, a chamber cutaway.

A Building is a footprint plus the art for "seen from outside" (roof) and "seen from
inside" (interior). Fully out draws the roof; fully in swaps to a baked copy with the
chamber punched out. In the doorway a line at the feet splits those two pictures
across the arch only.

Deliberately a leaf: geometry and a number. It knows nothing about the renderer, the
layout manager, or pygame beyond Rect/Mask, so it can be tested without a display.
"""

from Settings import TILESIZE
# Re-exported, not just imported: the door plane and its defaults were part of this module's
# surface before the geometry moved out, and tmx_layout_manager and the tests still import
# them from here.
from building_geometry import (  # noqa: F401
    DEFAULT_DOOR_DEPTH,
    DEFAULT_DOOR_GAP,
    arch_quad,
    clip_poly_halfplane,
    depth_along,
    door_plane_from_polygon,
)

import math
import pygame

# Stand-ins used until real art exists, so the mechanism is reviewable now. Filled
# through the footprint mask, never as a rectangle — a rect fill would turn a polygon
# building into a coloured AABB and hide exactly the shape we are trying to check.
PLACEHOLDER_ROOF_RGBA = (196, 158, 96, 255)
PLACEHOLDER_INTERIOR_RGBA = (44, 38, 34, 255)

VIEW_OUT = "out"
VIEW_DOOR = "door"
VIEW_IN = "in"

# Collision nudge at the outer lip only (out <-> door). door <-> in is a hard contains.
DOOR_LIP_JITTER = 8

# Disk masks for exit hysteresis. Keyed by radius so we do not rebuild a 150px
# circle every frame; dilating the AABB instead would keep you "inside" in the
# desert corners of a diamond chamber.
_DISK_MASKS = {}


def _disk_mask(radius):
    radius = int(radius)
    cached = _DISK_MASKS.get(radius)
    if cached is not None:
        return cached
    d = radius * 2 + 1
    surf = pygame.Surface((d, d), pygame.SRCALPHA)
    pygame.draw.circle(surf, (255, 255, 255, 255), (radius, radius), radius)
    cached = pygame.mask.from_surface(surf)
    _DISK_MASKS[radius] = cached
    return cached


def arch_aabb(quad):
    """Integer rect covering `quad`, padded a pixel so the polygon does not clip."""
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    left = int(math.floor(min(xs))) - 1
    top = int(math.floor(min(ys))) - 1
    right = int(math.ceil(max(xs))) + 1
    bottom = int(math.ceil(max(ys))) + 1
    return pygame.Rect(left, top, max(1, right - left), max(1, bottom - top))


class Building:
    def __init__(
        self,
        footprint,
        roof,
        interior,
        mask=None,
        chamber_rect=None,
        chamber_mask=None,
        roof_open=None,
        hysteresis_margin=TILESIZE,
        door_origin=None,
        door_inward=None,
        door_depth=DEFAULT_DOOR_DEPTH,
        arch_quad=None,
        door_lip_jitter=DOOR_LIP_JITTER,
    ):
        self.footprint = footprint
        self.roof = roof
        self.interior = interior
        self.mask = mask
        # No chamber authored: the footprint is the room, so the open roof is empty.
        if roof_open is None:
            roof_open = roof.copy()
            roof_open.fill((0, 0, 0, 0))
        self.roof_open = roof_open

        # The chamber is the room you can actually stand in, authored separately from
        # the silhouette. It has to be separate: a solid building's outline is mostly
        # its exterior surface, so triggering on the outline opens a hole through the
        # outside face as soon as you walk up to the door. Falls back to the whole
        # footprint for simple buildings whose outline IS their interior.
        self.chamber_rect = chamber_rect if chamber_rect is not None else footprint
        self.chamber_mask = chamber_mask if chamber_rect is not None else mask

        self.hysteresis_margin = int(hysteresis_margin)
        self.view = VIEW_OUT

        self.door_origin = door_origin
        self.door_inward = door_inward
        self.door_depth = float(door_depth)
        self.arch_quad = arch_quad
        self.arch_rect = arch_aabb(arch_quad) if arch_quad is not None else None
        self.door_lip_jitter = float(door_lip_jitter)
        self.split_depth = 0.0

    @property
    def inside(self):
        return self.view == VIEW_IN

    def depth(self, point):
        if self.door_origin is None:
            return 0.0
        return depth_along(point, self.door_origin, self.door_inward)

    def contains(self, point, margin=0):
        """Is `point` (world px) inside the chamber, optionally grown by `margin`?

        Exit hysteresis has to follow the chamber *shape*, not its AABB: a diamond
        pyramid's bounding box is mostly desert, and skipping the mask would leave
        the roof cut away after you walk out the door.
        """
        rect = self.chamber_rect
        if margin:
            if not rect.inflate(margin * 2, margin * 2).collidepoint(point):
                return False
            if self.chamber_mask is None:
                return True
            disk = _disk_mask(margin)
            offset = (int(point[0]) - margin - rect.x, int(point[1]) - margin - rect.y)
            return self.chamber_mask.overlap(disk, offset) is not None
        if not rect.collidepoint(point):
            return False
        if self.chamber_mask is None:
            return True
        # Only safe because the rect test above already bounded the point — get_at
        # raises IndexError outside the mask.
        local = (int(point[0]) - rect.x, int(point[1]) - rect.y)
        return bool(self.chamber_mask.get_at(local))

    def update(self, dt, point):
        """Set view from the camera subject's feet.

        No door plane: entry is the chamber, exit is the chamber inflated by a tile
        (the old boolean, so a doorway without a plane does not flicker).

        With a door plane: in beats door beats out. in is a hard contains (no TILESIZE
        latch through the arch). out <-> door jitters a few pixels at the outer lip.
        `dt` is unused; the signature matches the camera loop.
        """
        if self.door_origin is None:
            if self.view == VIEW_IN:
                self.view = VIEW_IN if self.contains(point, margin=self.hysteresis_margin) else VIEW_OUT
            else:
                self.view = VIEW_IN if self.contains(point) else VIEW_OUT
            return

        self.split_depth = self.depth(point)
        if self.contains(point):
            self.view = VIEW_IN
            return
        d = self.split_depth
        if self.view == VIEW_DOOR:
            if -self.door_lip_jitter <= d < self.door_depth:
                self.view = VIEW_DOOR
            else:
                self.view = VIEW_OUT
        elif 0.0 <= d < self.door_depth:
            self.view = VIEW_DOOR
        else:
            self.view = VIEW_OUT

    def far_arch_patch(self):
        """Interior crop of arch ∩ far half-plane, or None.

        Small on purpose: the arch AABB, not the footprint. Caller blits with no
        cache_key so this is not uploaded as a 11 M px scratch texture.
        """
        if (self.view != VIEW_DOOR or self.arch_quad is None or self.arch_rect is None
                or self.door_origin is None):
            return None
        clipped = clip_poly_halfplane(
            self.arch_quad, self.door_origin, self.door_inward, self.split_depth)
        if len(clipped) < 3:
            return None
        aabb = self.arch_rect
        crop = pygame.Rect(
            aabb.x - self.footprint.x, aabb.y - self.footprint.y, aabb.w, aabb.h)
        crop = crop.clip(self.interior.get_rect())
        if crop.width <= 0 or crop.height <= 0:
            return None
        patch = self.interior.subsurface(crop).copy()
        mask = pygame.Surface(patch.get_size(), pygame.SRCALPHA)
        origin_x = self.footprint.x + crop.x
        origin_y = self.footprint.y + crop.y
        pts = [(int(round(x - origin_x)), int(round(y - origin_y))) for x, y in clipped]
        if len(pts) >= 3:
            pygame.draw.polygon(mask, (255, 255, 255, 255), pts)
        patch.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        return patch, (origin_x, origin_y)
