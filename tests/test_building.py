"""Building cutaway logic: containment, the door cover, and the opt-in wedge reveal."""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Code"))

from Building import (  # noqa: E402
    DEFAULT_DOOR_DEPTH,
    DOOR_MODE_WEDGE,
    VIEW_DOOR,
    VIEW_IN,
    VIEW_OUT,
    Building,
    arch_quad,
    assemble,
    door_cover,
    door_plane_from_polygon,
)


def _surf(w=40, h=30):
    return pygame.Surface((w, h), pygame.SRCALPHA)


def _building(**kwargs):
    footprint = kwargs.pop("footprint", pygame.Rect(100, 100, 40, 30))
    return Building(footprint, _surf(), _surf(), **kwargs)


def _south_door_building(chamber_bottom=61, **kwargs):
    """80x80 footprint, door on the south edge, inward -Y, depth 20 meets y=60."""
    footprint = kwargs.pop("footprint", pygame.Rect(0, 0, 80, 80))
    origin = (40.0, 80.0)
    inward = (0.0, -1.0)
    tangent = (1.0, 0.0)
    door_depth = kwargs.pop("door_depth", 20.0)
    chamber = kwargs.pop("chamber_rect", pygame.Rect(10, 0, 60, chamber_bottom))
    kwargs.setdefault("chamber_mask", pygame.Mask(chamber.size, fill=True))
    kwargs.setdefault("door_lip_jitter", 8)
    # The three-state tests below were written for the sliding reveal, which is the
    # opt-in; the default ignores the door plane entirely. Pin it.
    kwargs.setdefault("door_mode", DOOR_MODE_WEDGE)
    return Building(
        footprint, _surf(80, 80), _surf(80, 80),
        door_origin=origin, door_inward=inward, door_depth=door_depth,
        arch_quad=arch_quad(origin, inward, tangent, 40, door_depth),
        chamber_rect=chamber,
        hysteresis_margin=kwargs.pop("hysteresis_margin", 0),
        **kwargs,
    )


def test_contains_rect_footprint():
    b = _building()
    assert b.contains((120, 115))
    assert not b.contains((99, 115))
    assert not b.contains((120, 131))


def test_contains_uses_mask_inside_the_rect():
    footprint = pygame.Rect(100, 100, 40, 30)
    mask = pygame.Mask((40, 30))
    mask.set_at((5, 5))  # a single opaque pixel
    b = _building(footprint=footprint, mask=mask)
    assert b.contains((105, 105))
    # Inside the rect but transparent -> not inside the building.
    assert not b.contains((130, 120))


def test_contains_never_indexes_the_mask_out_of_bounds():
    """The rect test must gate get_at, which raises outside the mask."""
    footprint = pygame.Rect(100, 100, 40, 30)
    mask = pygame.Mask((40, 30), fill=True)
    b = _building(footprint=footprint, mask=mask)
    for point in [(0, 0), (-5000, -5000), (99, 99), (141, 131), (10 ** 6, 10 ** 6)]:
        assert b.contains(point) is False


def test_margin_widens_containment():
    b = _building()
    outside = (145, 115)
    assert not b.contains(outside)
    assert b.contains(outside, margin=10)


def test_hysteresis_holds_inside_across_the_threshold():
    """Enter on the footprint; do not leave until a margin beyond it."""
    b = _building(hysteresis_margin=20)

    b.update(0.016, (120, 115))          # step in
    assert b.inside

    b.update(0.016, (145, 115))          # just outside the footprint, inside the band
    assert b.inside, "should not exit inside the hysteresis band"

    b.update(0.016, (175, 115))          # clear of the band
    assert not b.inside


def test_entry_has_no_latency():
    """Entry uses the footprint itself, so it latches on the first frame inside."""
    b = _building(hysteresis_margin=20)
    b.update(0.016, (101, 101))
    assert b.inside


def test_chamber_gates_the_cutaway_not_the_silhouette():
    """A solid building's outline is mostly exterior; only the room may open."""
    footprint = pygame.Rect(0, 0, 400, 400)
    chamber = pygame.Rect(150, 150, 100, 100)
    b = Building(footprint, _surf(), _surf(), mask=pygame.Mask((400, 400), fill=True),
                 chamber_rect=chamber, chamber_mask=pygame.Mask((100, 100), fill=True))
    assert b.contains((200, 200)), "inside the chamber"
    assert not b.contains((20, 20)), "on the silhouette but outside the room"
    b.update(0.016, (20, 20))
    assert not b.inside, "walking the outer face must not open the roof"
    b.update(0.016, (200, 200))
    assert b.inside


def test_chamber_defaults_to_the_footprint():
    """Simple buildings whose outline is their interior need no chamber."""
    b = _building()
    assert b.chamber_rect is b.footprint
    b.update(0.016, b.footprint.center)
    assert b.inside


def test_chamber_exit_follows_the_mask_not_the_aabb():
    """Desert in a diamond's bounding box is not still inside the building."""
    footprint = pygame.Rect(0, 0, 400, 400)
    chamber = pygame.Rect(0, 0, 400, 400)
    mask = pygame.Mask((400, 400))
    # Only the centre 80x80 is the room; the rest of the AABB is empty.
    for x in range(160, 240):
        for y in range(160, 240):
            mask.set_at((x, y))
    b = Building(footprint, _surf(400, 400), _surf(400, 400),
                 chamber_rect=chamber, chamber_mask=mask, hysteresis_margin=20)
    b.update(0.016, (200, 200))
    assert b.inside
    b.update(0.016, (20, 20))  # in the AABB, outside the room, far from the edge
    assert not b.inside, "leaving the room must close the roof even inside the AABB"


def test_missing_roof_open_is_a_fully_punched_copy():
    """No baked cutaway: the room is the whole footprint, so the open roof is empty."""
    b = _building()
    assert b.roof_open.get_size() == b.roof.get_size()
    assert b.roof_open.get_at((0, 0))[3] == 0


def test_door_plane_projects_onto_the_nearest_edge():
    """Raw (8430, 4970) is 207 px inward; the origin must sit on the SE face."""
    corners = [(7620, 2690), (9450, 4410), (7700, 5830), (5850, 4170)]
    authored = (8430, 4970)
    origin, inward, _quad = door_plane_from_polygon(corners, authored)
    se_a, se_b = corners[1], corners[2]
    # Origin is on B->C (perpendicular distance ~0), not the authored interior point.
    ex, ey = se_b[0] - se_a[0], se_b[1] - se_a[1]
    length = (ex * ex + ey * ey) ** 0.5
    t = ((origin[0] - se_a[0]) * ex + (origin[1] - se_a[1]) * ey) / (length * length)
    on_edge = (se_a[0] + t * ex, se_a[1] + t * ey)
    assert abs(origin[0] - on_edge[0]) < 1 and abs(origin[1] - on_edge[1]) < 1
    offset = ((authored[0] - origin[0]) ** 2 + (authored[1] - origin[1]) ** 2) ** 0.5
    assert 200 < offset < 215
    # Inward points into the diamond, not out into the desert.
    centre = (sum(p[0] for p in corners) / 4.0, sum(p[1] for p in corners) / 4.0)
    assert (centre[0] - origin[0]) * inward[0] + (centre[1] - origin[1]) * inward[1] > 0


def test_door_view_out_door_in_precedence():
    b = _south_door_building()
    b.update(0.016, (40, 90))
    assert b.view == VIEW_OUT and not b.inside
    b.update(0.016, (40, 70))  # depth 10, in the arch, not chamber
    assert b.view == VIEW_DOOR and not b.inside
    b.update(0.016, (40, 30))  # chamber
    assert b.view == VIEW_IN and b.inside


def test_in_beats_door_when_chamber_overlaps_the_band():
    # Chamber extends into the arch so a point is both contains and 0 <= depth < door_depth.
    b = _south_door_building(chamber_bottom=75)
    b.update(0.016, (40, 70))  # depth 10, y=70 is inside chamber [0, 75)
    assert b.contains((40, 70))
    assert 0 <= b.depth((40, 70)) < b.door_depth
    assert b.view == VIEW_IN


def test_door_depth_first_non_door_is_in_not_out():
    """At depth == door_depth, contains must be true — otherwise a roof sliver."""
    b = _south_door_building()
    # y = 80 - 20 = 60
    feet = (40, 60)
    assert abs(b.depth(feet) - b.door_depth) < 1e-6
    assert b.contains(feet), "inset and door_depth must meet"
    b.update(0.016, feet)
    assert b.view == VIEW_IN


def test_walking_out_the_arch_is_door_not_latched_in():
    b = _south_door_building()
    b.update(0.016, (40, 30))
    assert b.view == VIEW_IN
    b.update(0.016, (40, 70))  # back in the arch; TILESIZE latch would still be in
    assert b.view == VIEW_DOOR


def test_out_door_jitter_only_at_the_outer_lip():
    b = _south_door_building()
    b.update(0.016, (40, 79))  # depth 1 -> door
    assert b.view == VIEW_DOOR
    b.update(0.016, (40, 84))  # depth -4, still within jitter 8
    assert b.view == VIEW_DOOR
    b.update(0.016, (40, 90))  # depth -10, clear of the lip
    assert b.view == VIEW_OUT
    b.update(0.016, (40, 84))  # approaching from out: depth -4 is not yet >= 0
    assert b.view == VIEW_OUT
    b.update(0.016, (40, 79))
    assert b.view == VIEW_DOOR


def test_no_door_plane_keeps_tilesize_hysteresis():
    """Existing boolean path: no door plane never enters VIEW_DOOR."""
    b = _building(hysteresis_margin=20)
    b.update(0.016, (120, 115))
    assert b.view == VIEW_IN
    assert b.view != VIEW_DOOR


def test_wedge_mode_still_available_per_building():
    b = _south_door_building(door_mode=DOOR_MODE_WEDGE)
    b.update(0.016, (40, 70))
    assert b.view == VIEW_DOOR
    assert b.far_arch_patch() is not None


# ---------------------------------------------------------------- the default: feet in the chamber

def test_default_mode_is_feet_in_the_chamber():
    """With a door plane authored and no door_mode, the plane is ignored: feet in the arch
    but short of the chamber are OUT, feet in the chamber are IN, and nothing is ever DOOR."""
    b = _south_door_building(door_mode=None)
    seen = []
    for y in (90, 79, 70, 61, 30):          # outside -> lip -> arch -> chamber edge -> chamber
        b.update(0.016, (40, y))
        seen.append(b.view)
        assert b.far_arch_patch() is None, "the default must never yield a wedge"
    assert VIEW_DOOR not in seen
    assert seen[:3] == [VIEW_OUT, VIEW_OUT, VIEW_OUT], "the arch is not the room"
    assert seen[-1] == VIEW_IN
    assert b.door_mode is None


def test_invalid_door_mode_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        _south_door_building(door_mode="threshold")


def _shaped_roof(footprint, mask):
    roof = pygame.Surface(footprint.size, pygame.SRCALPHA)
    roof.fill((200, 100, 50, 255))
    roof.blit(mask.to_surface(setcolor=(255, 255, 255, 255), unsetcolor=(0, 0, 0, 0)),
              (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return roof


def test_door_cover_is_the_roofs_pixels_inside_the_polygon():
    """A triangular door straddling the silhouette's bottom edge: roof pixels inside the
    polygon and the silhouette, transparent on the overhang and outside the polygon."""
    footprint = pygame.Rect(100, 100, 80, 60)
    silhouette = pygame.Mask((80, 60), fill=True)
    for x in range(80):                      # bottom 10 rows are outside the building
        for y in range(50, 60):
            silhouette.set_at((x, y), 0)
    roof = _shaped_roof(footprint, silhouette)
    # Door polygon: a triangle from (130,140)-(150,140) up to (140,120), then hanging down
    # to y=158 -- the bottom 8 px of it are on the sand.
    door_rect = pygame.Rect(130, 120, 20, 38)
    door_surf = pygame.Surface(door_rect.size, pygame.SRCALPHA)
    pygame.draw.polygon(door_surf, (255, 255, 255, 255), [(10, 0), (20, 20), (20, 38), (0, 38), (0, 20)])
    door_mask = pygame.mask.from_surface(door_surf)

    rect, cover = door_cover(footprint, roof, door_rect, door_mask)

    assert rect == door_rect, "cropped to the door, not the footprint"
    assert cover.get_at((10, 15))[3] == 255, "inside the polygon and the building"
    assert cover.get_at((10, 34))[3] == 0, "the overhang onto the sand is transparent"
    assert cover.get_at((1, 2))[3] == 0, "outside the polygon is transparent"
    assert cover.get_at((10, 15))[:3] == (200, 100, 50), "the roof's own pixels"


def test_door_cover_is_none_when_the_door_misses_the_building():
    footprint = pygame.Rect(100, 100, 80, 60)
    roof = _shaped_roof(footprint, pygame.Mask((80, 60), fill=True))
    door_rect = pygame.Rect(300, 300, 20, 20)
    assert door_cover(footprint, roof, door_rect, pygame.Mask((20, 20), fill=True)) is None


def test_assemble_punches_the_chamber_and_clips_the_interior():
    footprint = pygame.Rect(0, 0, 80, 80)
    mask = pygame.Mask((80, 80), fill=True)
    roof = _shaped_roof(footprint, mask)
    interior = pygame.Surface(footprint.size, pygame.SRCALPHA)
    interior.fill((30, 80, 180, 255))
    chamber = (pygame.Rect(20, 20, 30, 30), pygame.Mask((30, 30), fill=True))

    b = assemble(footprint, mask, roof, interior, chamber=chamber)

    assert b.roof_open.get_at((5, 5))[3] == 255, "the face around the room stays roof"
    assert b.roof_open.get_at((35, 35))[3] == 0, "the room is punched"
    assert b.interior.get_at((35, 35))[3] == 255, "interior shows in the room"
    assert b.interior.get_at((5, 5))[3] == 0, "and nowhere else"
    assert b.contains((35, 35)) and not b.contains((5, 5))
    assert b.door_mode is None


def test_inside_the_whole_silhouette_is_black():
    """Black right to the building's edge -- the room, the stone round it, the base -- and
    nothing past it."""
    footprint = pygame.Rect(0, 0, 80, 80)
    mask = pygame.Mask((80, 80))
    mask.draw(pygame.Mask((60, 60), fill=True), (10, 10))
    chamber = (pygame.Rect(20, 20, 30, 30), pygame.Mask((30, 30), fill=True))
    b = assemble(footprint, mask, _shaped_roof(footprint, mask),
                 pygame.Surface(footprint.size, pygame.SRCALPHA), chamber=chamber,
                 name="great_pyramid")
    assert tuple(b.black.get_at((15, 15))) == (0, 0, 0, 255), "the stone round the room"
    assert tuple(b.black.get_at((65, 65))) == (0, 0, 0, 255), "down to the base"
    assert tuple(b.black.get_at((35, 35))) == (0, 0, 0, 255), "under the room, drawn over it"
    assert b.black.get_at((5, 5))[3] == 0, "outside the building"
    assert b.name == "great_pyramid"


def test_the_interior_shows_on_the_floor_and_its_walls_only():
    """Inside, the painting shows on the floor and on the wall obstacles round it; the
    stone past them stays black."""
    footprint = pygame.Rect(0, 0, 80, 80)
    mask = pygame.Mask((80, 80), fill=True)
    interior = pygame.Surface(footprint.size, pygame.SRCALPHA)
    interior.fill((30, 80, 180, 255))
    chamber = (pygame.Rect(20, 20, 30, 30), pygame.Mask((30, 30), fill=True))
    wall = (pygame.Rect(50, 20, 10, 30), pygame.Mask((10, 30), fill=True))
    b = assemble(footprint, mask, _shaped_roof(footprint, mask), interior,
                 chamber=chamber, walls=[wall])
    assert b.interior.get_at((35, 35))[3] == 255, "the floor"
    assert b.interior.get_at((55, 35))[3] == 255, "its wall"
    assert b.interior.get_at((70, 35))[3] == 0, "the stone past the wall"


def test_assemble_without_a_chamber_uses_the_footprint():
    footprint = pygame.Rect(0, 0, 80, 80)
    mask = pygame.Mask((80, 80), fill=True)
    b = assemble(footprint, mask, _shaped_roof(footprint, mask),
                 pygame.Surface(footprint.size, pygame.SRCALPHA))
    assert b.roof_open.get_at((5, 5))[3] == 0, "no chamber: the whole footprint is the room"
    assert b.contains((5, 5))
