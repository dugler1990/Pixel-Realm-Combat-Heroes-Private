"""Where a hit landed: touch_point, find_contacts, entry_point (damage chunk 3)."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

import hit_core  # noqa: E402


def _mask_shape(w, h, x, y, fill=True):
    return hit_core.Shape(pygame.mask.Mask((w, h), fill=fill), x, y)


def _dot_shape(x, y):
    """A 1x1 shape: its only pixel is the contact."""
    return _mask_shape(1, 1, x, y)


def _in_shape(shape, point):
    x, y = point[0] - shape.rect.x, point[1] - shape.rect.y
    return 0 <= x < shape.rect.w and 0 <= y < shape.rect.h and shape.mask.get_at((x, y))


class _Body:
    def __init__(self, x, y, solid=True):
        self.rect = pygame.Rect(x, y, 10, 10)
        self.mask = pygame.mask.Mask((10, 10), fill=solid)


# --- touch_point -------------------------------------------------------------------------

def test_touch_point_is_the_shared_pixel_in_world_coords():
    body = _mask_shape(40, 40, 100, 200)
    assert hit_core.touch_point(_dot_shape(117, 223), body) == (117, 223)
    assert hit_core.touch_point(body, _dot_shape(117, 223)) == (117, 223)


def test_touch_point_none_when_nothing_is_shared():
    body = _mask_shape(40, 40, 100, 200)
    assert hit_core.touch_point(_dot_shape(10, 10), body) is None          # rects miss
    hollow = _mask_shape(40, 40, 100, 200, fill=False)
    assert hit_core.touch_point(_dot_shape(117, 223), hollow) is None      # rects meet, pixels don't
    assert hit_core.touch_point(None, body) is None


@pytest.mark.parametrize("a, b", [
    ((10, 10, 0, 0), (10, 10, 5, 5)),
    ((10, 10, 0, 0), (10, 10, 50, 50)),
    ((20, 4, 0, 0), (4, 20, 8, -8)),
])
def test_touching_agrees_with_touch_point(a, b):
    sa, sb = _mask_shape(*a), _mask_shape(*b)
    assert hit_core.touching(sa, sb) == (hit_core.touch_point(sa, sb) is not None)


def test_two_rect_bodies_meet_at_the_centre_of_their_overlap():
    a = hit_core.rect_shape(pygame.Rect(0, 0, 20, 20))
    b = hit_core.rect_shape(pygame.Rect(10, 6, 20, 20))
    assert a.solid and b.solid
    assert hit_core.touch_point(a, b) == pygame.Rect(10, 6, 10, 14).center


def test_rect_body_against_a_mask_gives_a_pixel_of_the_mask():
    rect_body = hit_core.rect_shape(pygame.Rect(0, 0, 40, 40))
    point = hit_core.touch_point(_dot_shape(31, 7), rect_body)
    assert point == (31, 7)


def test_mask_shapes_are_not_solid():
    assert _mask_shape(4, 4, 0, 0).solid is False


# --- find_contacts -----------------------------------------------------------------------

def test_find_contacts_matches_find_hits_and_points_lie_in_both_shapes():
    attack = _mask_shape(20, 20, 0, 0)
    near, also_near, owner = _Body(5, 5), _Body(12, 0), _Body(0, 0)
    far, hollow = _Body(100, 100), _Body(5, 5, solid=False)
    candidates = [far, near, hollow, object(), owner, near, also_near]
    hits = hit_core.find_hits(attack, candidates, exclude=(owner,))
    contacts = hit_core.find_contacts(attack, candidates, exclude=(owner,))
    assert [c[0] for c in contacts] == hits == [near, also_near]
    for sprite, point, body_shape in contacts:
        assert _in_shape(attack, point) and _in_shape(body_shape, point)
        assert body_shape.rect == sprite.rect


def test_find_contacts_with_a_footprint_body():
    attack = _mask_shape(20, 20, 0, 0)
    sprite = _Body(5, 5)
    contacts = hit_core.find_contacts(attack, [sprite], body=lambda s: _mask_shape(2, 2, 6, 6))
    assert contacts and contacts[0][1] == (6, 6)


def test_find_contacts_none_shape():
    assert hit_core.find_contacts(None, [_Body(0, 0)]) == []


# --- entry_point -------------------------------------------------------------------------

BODY = (100, 200, 40, 40)   # x, y, w, h


def _body():
    return _mask_shape(BODY[2], BODY[3], BODY[0], BODY[1])


def test_shot_moving_right_enters_on_the_left_column():
    point = (BODY[0] + 9, BODY[1] + 17)
    assert hit_core.entry_point(point, (12, 0), _body()) == (BODY[0], BODY[1] + 17)


def test_shot_moving_left_enters_on_the_right_column():
    point = (BODY[0] + 30, BODY[1] + 5)
    assert hit_core.entry_point(point, (-12, 0), _body()) == (BODY[0] + BODY[2] - 1, BODY[1] + 5)


def test_shot_moving_down_enters_on_the_top_row():
    point = (BODY[0] + 20, BODY[1] + 11)
    assert hit_core.entry_point(point, (0, 12), _body()) == (BODY[0] + 20, BODY[1])


def test_diagonal_shot_enters_on_the_outline_near_its_line():
    body = _body()
    point = (BODY[0] + 20, BODY[1] + 12)
    ex, ey = hit_core.entry_point(point, (8, 8), body)
    assert _in_shape(body, (ex, ey))
    assert ex == BODY[0] + 8 and ey == BODY[1]          # back 12 along (-1,-1)/sqrt2 hits the top row
    # On the line through point with slope 1, within a pixel.
    assert abs((point[0] - ex) - (point[1] - ey)) <= 1


def test_ring_body_stops_at_the_outer_edge_not_the_hole():
    surf = pygame.Surface((40, 40), pygame.SRCALPHA)
    pygame.draw.circle(surf, (255, 255, 255, 255), (20, 20), 20)
    pygame.draw.circle(surf, (0, 0, 0, 0), (20, 20), 8)
    ring = hit_core.Shape(pygame.mask.from_surface(surf), 0, 0)
    # Shot moving left; overlap pixel on the ring's right side, outside the hole.
    point = (34, 20)
    assert ring.mask.get_at(point)
    ex, ey = hit_core.entry_point(point, (-12, 0), ring)
    assert ey == 20 and ex == 39                      # outer right edge
    # Moving right from the same pixel: walks back to the hole's edge, the first gap behind it.
    ex, _ = hit_core.entry_point(point, (12, 0), ring)
    hole_edge = next(x for x in range(20, 40) if ring.mask.get_at((x, 20)))
    assert ex == hole_edge and hole_edge < point[0]


def test_entry_point_respects_max_steps_and_the_cap():
    big = _mask_shape(200, 10, 0, 0)
    assert hit_core.entry_point((150, 5), (1, 0), big, max_steps=10) == (140, 5)
    assert hit_core.entry_point((150, 5), (1, 0), big, max_steps=500) == (86, 5)   # capped at 64


def test_entry_point_returns_the_point_when_it_cannot_walk():
    body = _body()
    assert hit_core.entry_point((110, 210), (0, 0), body) == (110, 210)
    assert hit_core.entry_point((5, 5), (1, 0), body) == (5, 5)          # not on the body
    assert hit_core.entry_point((110, 210), (1, 0), None) == (110, 210)
