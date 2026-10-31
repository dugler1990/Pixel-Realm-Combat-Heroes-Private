"""Authored building interiors: one region, two looks, a chamber you stand in.

A Building is a footprint plus the art for "seen from outside" (roof) and "seen from
inside" (interior). Outside draws the roof. Inside draws no roof at all: the whole building
is black, its floor shows the interior painting, and floor you have not explored yet stays
black (InteriorFog). Two states, and one rule for which you are in: your feet are in the
chamber or they are not. The chamber is the floor the pipeline traced from the painting.

The door is not part of this class. It is a canopy: the layout manager registers the
exterior's own door pixels as an overhead area, and the camera draws that over the player
when his rect is in it -- the same hide-behind-object rule trees use -- so a body walking
in goes under the painted door.

Wedge (`door_mode="wedge"`) is the opt-in third state: between the door plane and
`door_depth` a sliver of interior is revealed through the arch, clipped at your feet, and
grows as you walk in. Kept for buildings where a sliding reveal reads better than a cut;
off by default because the sliver is the model's door blended over the painted one.

Deliberately a leaf: geometry and a number. It knows nothing about the renderer or the
layout manager, and of pygame only Rect/Mask/Surface, so it can be tested without a
display. The surface assembly (`assemble`, `door_cover`) lives here for the same reason:
it is pure pygame, and the layout manager only has to load images and read tags.
"""

from Settings import INTERIOR_FOG, TILESIZE
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

# A patch walled in by chamber, walls and door frame under this share of the silhouette is
# a gap between them and shows the interior art (`_pockets`). On great_pyramid (2026-10-31)
# the gaps were 6k px at most and the doorway 33k, the stone between rooms 625k, of 5.7M.
POCKET_FRACTION = 0.01

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


def mask_of(rect, shapes):
    """One `rect`-sized mask covering every `(shape_rect, shape_mask)` in `shapes` (world
    px); a shape mask of None covers its whole rect."""
    out = pygame.Mask(rect.size)
    for shape_rect, shape_mask in shapes:
        if shape_mask is None:
            shape_mask = pygame.Mask(shape_rect.size, fill=True)
        out.draw(shape_mask, (shape_rect.x - rect.x, shape_rect.y - rect.y))
    return out


def black_silhouette(footprint, mask):
    """Footprint-sized surface: opaque black where `mask` covers, else clear."""
    if mask is None:
        black = pygame.Surface(footprint.size, pygame.SRCALPHA)
        black.fill((0, 0, 0, 255))
        return black
    return mask.to_surface(setcolor=(0, 0, 0, 255), unsetcolor=(0, 0, 0, 0))


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


def _pockets(footprint, mask, covered):
    """Footprint-sized mask of the small patches of the silhouette that `covered` encloses.

    The chamber is traced from the plan and the walls are SAM's, so they never quite meet:
    the chamber's corners are round where the painted walls are square, and the stone the
    door rule drops (interiors `sam_room`) is in neither. Each gap is a small patch of the
    silhouette walled in by the two; the stone between rooms and the building's outer face
    are a few patches far bigger than any of them.
    """
    uncovered = mask.copy() if mask is not None else pygame.Mask(footprint.size, fill=True)
    biggest_pocket = int(uncovered.count() * POCKET_FRACTION)
    uncovered.erase(covered, (0, 0))
    pockets = uncovered.copy()
    for big in uncovered.connected_components(biggest_pocket):
        pockets.erase(big, (0, 0))
    return pockets


def assemble(footprint, mask, roof, interior, chamber=None, arch_quad=None,
             hysteresis_margin=TILESIZE, name=None, walls=(), doors=(), **door_plane):
    """A Building from loaded art and authored shapes.

    `chamber` is `(rect, mask)` in world px or None -- the floor you can stand on, the
    trigger for going inside. No chamber: the footprint is the floor. `walls` are the
    building's wall obstacles and `doors` its door frame, `(rect, mask)` pieces in world px.
    `roof` and `interior` are footprint-sized and already clipped to the silhouette. The
    interior is clipped to the floor, its walls, the door frame and the gaps they enclose
    (`_pockets`), plus the arch when a door plane is authored, so wedge mode has floor pixels
    in the doorway; inside, everything else is black. roof_open, the roof with the chamber
    punched out, is the wedge's door view.

    `name` is the map object's, which a prop's `building` tag names.

    `door_plane` is passed through untouched (`door_origin`, `door_inward`, `door_depth`,
    `door_mode`, `door_lip_jitter`).
    """
    chamber_rect, chamber_mask = chamber if chamber is not None else (None, None)
    chamber_clip = clip_surface(
        footprint,
        chamber_rect if chamber_rect is not None else footprint,
        chamber_mask if chamber_rect is not None else mask,
    )
    walls_mask = mask_of(footprint, walls) if walls else None
    doors_mask = mask_of(footprint, doors) if doors else None
    if walls_mask is not None and chamber_rect is not None:
        # The gaps count as walls, so the fog keeps them dark until they are explored too.
        covered = mask_of(footprint, [(chamber_rect, chamber_mask), *walls, *doors])
        walls_mask.draw(_pockets(footprint, mask, covered), (0, 0))
    interior_clip = chamber_clip
    if walls_mask is not None or doors_mask is not None or arch_quad is not None:
        interior_clip = chamber_clip.copy()
    for shown in (walls_mask, doors_mask):
        if shown is not None:
            interior_clip.blit(clip_surface(footprint, footprint, shown), (0, 0),
                               special_flags=pygame.BLEND_RGBA_MAX)
    if arch_quad is not None:
        or_polygon_into_clip(interior_clip, footprint, arch_quad)
    interior = interior.copy()
    interior.blit(interior_clip, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    building = Building(
        footprint, roof, interior, mask=mask, name=name,
        chamber_rect=chamber_rect, chamber_mask=chamber_mask,
        roof_open=roof_with_chamber_punched(roof, chamber_clip),
        arch_quad=arch_quad, hysteresis_margin=hysteresis_margin,
        **door_plane,
    )
    if INTERIOR_FOG:
        from interior_visibility import InteriorFog
        floor = mask_of(footprint, [(building.chamber_rect, building.chamber_mask)])
        building.fog = InteriorFog(footprint, floor, walls_mask)
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
        name=None,
    ):
        self.name = name
        self.footprint = footprint
        self.roof = roof
        self.interior = interior
        self.mask = mask
        # No chamber authored: the footprint is the room, so the open roof is empty.
        if roof_open is None:
            roof_open = roof.copy()
            roof_open.fill((0, 0, 0, 0))
        self.roof_open = roof_open
        # Inside, the building is black but for its floor: the ground under it has the
        # outside painted on it, and the stone between rooms is nowhere you can go. Drawn
        # under the bodies, so one you can see is never cut off at the edge of a room.
        self.black = black_silhouette(footprint, mask)

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
        # Set by assemble() when INTERIOR_FOG is on. None shows the whole floor.
        self.fog = None

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
            self._explore(point)
            return
        if self.view == VIEW_IN:
            self.view = VIEW_IN if self.contains(point, margin=self.hysteresis_margin) else VIEW_OUT
        else:
            self.view = VIEW_IN if self.contains(point) else VIEW_OUT
        self._explore(point)

    def _explore(self, point):
        if self.fog is not None and self.view == VIEW_IN:
            self.fog.explore_from(point)

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
