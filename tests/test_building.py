"""Building cutaway logic: containment, door plane, and doorway hysteresis."""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Code"))

from Building import (  # noqa: E402
    DEFAULT_DOOR_DEPTH,
    VIEW_DOOR,
    VIEW_IN,
    VIEW_OUT,
    Building,
    arch_quad,
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


def test_sunspine_pyramid_door_depth_meets_chamber():
    """Load-bearing TMX invariant: origin + door_depth * inward is inside the chamber."""
    corners = [(7620, 2690), (9450, 4410), (7700, 5830), (5850, 4170)]
    origin, inward, _quad = door_plane_from_polygon(corners, (8430, 4970), DEFAULT_DOOR_DEPTH)
    inner = (origin[0] + inward[0] * DEFAULT_DOOR_DEPTH,
             origin[1] + inward[1] * DEFAULT_DOOR_DEPTH)
    chamber_origin = (6094, 2904)
    rel = [(1520, 0), (3113, 1497), (1611, 2716), (0, 1270)]
    world = [(chamber_origin[0] + x, chamber_origin[1] + y) for x, y in rel]
    xs = [p[0] for p in world]
    ys = [p[1] for p in world]
    left, top = int(min(xs)), int(min(ys))
    surf = pygame.Surface((int(max(xs)) - left + 2, int(max(ys)) - top + 2), pygame.SRCALPHA)
    pygame.draw.polygon(surf, (255, 255, 255, 255),
                        [(int(x - left), int(y - top)) for x, y in world])
    mask = pygame.mask.from_surface(surf)
    local = (int(round(inner[0])) - left, int(round(inner[1])) - top)
    assert 0 <= local[0] < mask.get_size()[0] and 0 <= local[1] < mask.get_size()[1]
    assert mask.get_at(local), "door_depth %s does not meet the chamber inset" % DEFAULT_DOOR_DEPTH
