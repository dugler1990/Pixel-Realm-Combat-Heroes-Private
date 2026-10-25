"""Authored building interiors: one region, two surfaces, a chamber cutaway.

A Building is a footprint plus the art for "seen from outside" (roof) and "seen from
inside" (interior). Fully out draws the roof; fully in swaps to a baked copy with the
chamber punched out. Two states, and one rule for which you are in: your feet are in the
chamber or they are not. The chamber is the room the pipeline traced from the painting.

Once inside, InteriorSight (see that module) blacks out floor the subject cannot
see: walls block, unseen rooms stay dark. The cutaway is still the whole chamber;
sight is a shutter over the painting, not a second hole in the roof.

The door is not part of this class. It is a canopy: the layout manager registers the
exterior's own door pixels as an overhead area, and the camera draws that over the player
when his rect is in it -- the same hide-behind-object rule trees use -- so a body walking
in goes under the painted door and comes back out through the hole in the roof.

Wedge (`door_mode="wedge"`) is the opt-in third state: between the door plane and
`door_depth` a sliver of interior is revealed through the arch, clipped at your feet, and
grows as you walk in. Kept for buildings where a sliding reveal reads better than a cut;
off by default because the sliver is the model's door blended over the painted one.

Deliberately a leaf: geometry and a number. It knows nothing about the renderer or the
layout manager, and of pygame only Rect/Mask/Surface, so it can be tested without a
display. The surface assembly (`assemble`, `door_cover`) lives here for the same reason:
it is pure pygame, and the layout manager only has to load images and read tags.
"""

from Settings import INTERIOR_SIGHT, TILESIZE
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

# The one opt-in door mode. Unset means the default: inside is the chamber, the door is a
# canopy, and the door plane (if authored) only clips the interior art.
DOOR_MODE_WEDGE = "wedge"

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


def _mask_contains(rect, mask, point, margin=0):
    """Is `point` (world px) inside `mask` at `rect`, optionally grown by `margin`?

    Hysteresis has to follow the *shape*, not the AABB: a diamond pyramid's bounding box
    is mostly desert, and skipping the mask would leave the roof cut away after you walk
    out the door. A `mask` of None means the rect is the shape.
    """
    if rect is None:
        return False
    if margin:
        if not rect.inflate(margin * 2, margin * 2).collidepoint(point):
            return False
        if mask is None:
            return True
        disk = _disk_mask(margin)
        offset = (int(point[0]) - margin - rect.x, int(point[1]) - margin - rect.y)
        return mask.overlap(disk, offset) is not None
    if not rect.collidepoint(point):
        return False
    if mask is None:
        return True
    # Only safe because the rect test above already bounded the point — get_at
    # raises IndexError outside the mask.
    local = (int(point[0]) - rect.x, int(point[1]) - rect.y)
    return bool(mask.get_at(local))


def arch_aabb(quad):
    """Integer rect covering `quad`, padded a pixel so the polygon does not clip."""
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    left = int(math.floor(min(xs))) - 1
    top = int(math.floor(min(ys))) - 1
    right = int(math.ceil(max(xs))) + 1
    bottom = int(math.ceil(max(ys))) + 1
    return pygame.Rect(left, top, max(1, right - left), max(1, bottom - top))


# ---------------------------------------------------------------- surface assembly

def clip_surface(footprint, shape_rect, shape_mask):
    """Footprint-sized alpha stencil: opaque where `shape_mask` covers, else clear."""
    clip = pygame.Surface(footprint.size, pygame.SRCALPHA)
    if shape_mask is None:
        clip.fill((255, 255, 255, 255))
        return clip
    shape = shape_mask.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0))
    clip.blit(shape, (shape_rect.x - footprint.x, shape_rect.y - footprint.y))
    return clip


def or_polygon_into_clip(clip, footprint, world_verts):
    """Make `clip` also opaque inside `world_verts` (footprint-local polygon)."""
    pts = [(int(round(x - footprint.x)), int(round(y - footprint.y))) for x, y in world_verts]
    if len(pts) >= 3:
        pygame.draw.polygon(clip, (255, 255, 255, 255), pts)


def roof_with_chamber_punched(roof, chamber_clip):
    """Copy of `roof` with chamber alpha zeroed. Outer walls stay."""
    inverted = pygame.Surface(roof.get_size(), pygame.SRCALPHA)
    inverted.fill((255, 255, 255, 255))
    inverted.blit(chamber_clip, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)
    roof_open = roof.copy()
    roof_open.blit(inverted, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return roof_open


def door_cover(footprint, roof, door_rect, door_mask):
    """The exterior's own door pixels, as an overhead area: (world rect, surface) or None.

    `roof` is footprint-sized and already clipped to the silhouette, so the part of a
    door polygon that hangs off the building onto the sand comes out transparent and the
    cover is exactly exterior ∩ door ∩ silhouette. Cropped to the door's rect, because an
    overhead area is drawn whenever the player's rect touches its rect, and a
    footprint-sized rect would put the door over him anywhere in the building.
    """
    local = door_rect.move(-footprint.x, -footprint.y).clip(roof.get_rect())
    if local.width <= 0 or local.height <= 0:
        return None
    cover = roof.subsurface(local).copy()
    world = local.move(footprint.x, footprint.y)
    cover.blit(clip_surface(world, door_rect, door_mask), (0, 0),
               special_flags=pygame.BLEND_RGBA_MULT)
    if pygame.mask.from_surface(cover).count() == 0:
        return None
    return world, cover


def assemble(footprint, mask, roof, interior, chamber=None, arch_quad=None,
             hysteresis_margin=TILESIZE, **door_plane):
    """A Building from loaded art and authored shapes.

    `chamber` is `(rect, mask)` in world px or None -- the room you can stand in, the
    trigger for the cutaway and the hole in the roof. No chamber: the footprint is the
    room, so the open roof is empty. `roof` and `interior` are footprint-sized and already
    clipped to the silhouette. The interior is clipped to the chamber (plus the arch, when
    a door plane is authored, so wedge mode has floor pixels in the doorway); the roof
    keeps everything but the chamber.

    `door_plane` is passed through untouched (`door_origin`, `door_inward`, `door_depth`,
    `door_mode`, `door_lip_jitter`).
    """
    chamber_rect, chamber_mask = chamber if chamber is not None else (None, None)
    chamber_clip = clip_surface(
        footprint,
        chamber_rect if chamber_rect is not None else footprint,
        chamber_mask if chamber_rect is not None else mask,
    )
    interior_clip = chamber_clip
    if arch_quad is not None:
        interior_clip = chamber_clip.copy()
        or_polygon_into_clip(interior_clip, footprint, arch_quad)
    interior = interior.copy()
    interior.blit(interior_clip, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    building = Building(
        footprint, roof, interior, mask=mask,
        chamber_rect=chamber_rect, chamber_mask=chamber_mask,
        roof_open=roof_with_chamber_punched(roof, chamber_clip),
        arch_quad=arch_quad, hysteresis_margin=hysteresis_margin,
        **door_plane,
    )
    if INTERIOR_SIGHT:
        from interior_visibility import InteriorSight
        building.sight = InteriorSight.from_chamber(
            building.chamber_rect, building.chamber_mask)
    return building


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
        door_mode=None,
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
        if door_mode not in (None, DOOR_MODE_WEDGE):
            raise ValueError(f"door_mode must be None or {DOOR_MODE_WEDGE!r}, got {door_mode!r}")
        self.door_mode = door_mode
        # Set by assemble() when INTERIOR_SIGHT is on. Direct Building() calls in
        # tests leave this None and keep the old full-chamber reveal.
        self.sight = None

    @property
    def inside(self):
        return self.view == VIEW_IN

    def depth(self, point):
        if self.door_origin is None:
            return 0.0
        return depth_along(point, self.door_origin, self.door_inward)

    def contains(self, point, margin=0):
        """Is `point` (world px) inside the chamber, optionally grown by `margin`?"""
        return _mask_contains(self.chamber_rect, self.chamber_mask, point, margin)

    def update(self, dt, point):
        """Set view from the camera subject's feet.

        Default: in when the chamber contains the feet; on the way out the chamber is
        inflated by a tile, so standing on the edge does not flicker. The door needs no
        rule of its own -- the chamber the pipeline traced starts behind the painted door,
        and the door itself is drawn over you as a canopy.

        Wedge (opt-in, needs a door plane): in beats door beats out. in is a hard contains
        (no TILESIZE latch through the arch). out <-> door jitters a few pixels at the
        outer lip. `dt` is unused; the signature matches the camera loop.
        """
        if self.door_mode == DOOR_MODE_WEDGE and self.door_origin is not None:
            self.split_depth = self.depth(point)
            self._update_wedge(point)
            self._update_sight(point)
            return
        if self.view == VIEW_IN:
            self.view = VIEW_IN if self.contains(point, margin=self.hysteresis_margin) else VIEW_OUT
        else:
            self.view = VIEW_IN if self.contains(point) else VIEW_OUT
        self._update_sight(point)

    def _update_sight(self, point):
        if self.sight is None:
            return
        if self.view == VIEW_IN:
            self.sight.reveal_from(point)
        else:
            self.sight.hide()

    def _update_wedge(self, point):
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

        Wedge mode only: the default never enters VIEW_DOOR, so this is always None there.
        """
        if (self.door_mode != DOOR_MODE_WEDGE or self.view != VIEW_DOOR
                or self.arch_quad is None or self.arch_rect is None
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
