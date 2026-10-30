"""Interior sight: walls block sight, and nothing else does."""

import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np
import pygame
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Code"))

import Building as building_mod  # noqa: E402
from Building import assemble  # noqa: E402
from interior_visibility import InteriorSight, sight_ring, walls_from_loops  # noqa: E402
from render_backend import CPUBackend  # noqa: E402
from YsortCameraGroup import YSortCameraGroup  # noqa: E402


@pytest.fixture(autouse=True)
def _sight_on(monkeypatch):
    """Sight is off in Settings while black stone is tried; these test it switched on."""
    monkeypatch.setattr(building_mod, "INTERIOR_SIGHT", True)


def _init():
    pygame.display.init()
    pygame.display.set_mode((64, 64))


def _box(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# Two rooms side by side in a 400 x 200 hall, split by a 20 px partition with a doorway
# from y=80 to y=120.
_TWO_ROOMS = [_box(0, 0, 400, 200), _box(190, 0, 210, 80), _box(190, 120, 210, 200)]
# An L: a corridor along the top, turning down at its right-hand end.
_L_ROOM = [[(0, 0), (300, 0), (300, 300), (200, 300), (200, 100), (0, 100)]]


def _sight(loops, band=0.0, radius=1000.0, size=(400, 300)):
    _init()
    chamber = pygame.Rect((0, 0), size)
    return InteriorSight(chamber, pygame.Mask(size, fill=True), loops, band=band, radius=radius)


# ---------------------------------------------------------------- what is seen

def test_an_open_room_is_seen_corner_to_corner():
    sight = _sight([_box(0, 0, 200, 100)])
    sight.reveal_from((50, 50))
    for point in ((5, 5), (195, 5), (195, 95), (5, 95), (100, 50)):
        assert sight.sees(point), point


def test_open_floor_past_the_radius_is_not_seen():
    sight = _sight([_box(0, 0, 400, 100)], radius=150)
    sight.reveal_from((50, 50))
    assert sight.sees((190, 50))
    assert not sight.sees((250, 50))


def test_round_a_corner_is_dark():
    sight = _sight(_L_ROOM)
    sight.reveal_from((50, 50))
    assert sight.sees((250, 50)), "the turn itself is in view"
    assert sight.sees((280, 110)), "a little way down, along the far wall"
    assert not sight.sees((250, 280)), "the far end of the turn is round the corner"
    assert not sight.sees((220, 250))


def test_a_doorway_shows_a_wedge_of_the_next_room():
    sight = _sight(_TWO_ROOMS)
    sight.reveal_from((50, 100))
    assert sight.sees((300, 100)), "straight through the doorway"
    assert sight.sees((230, 95))
    assert not sight.sees((350, 30)), "behind the partition"
    assert not sight.sees((350, 180))


def test_the_face_of_a_wall_is_lit_to_the_band():
    lit = _sight([_box(0, 0, 200, 100)], band=10)
    lit.reveal_from((100, 50))
    assert lit.sees((100, 105))
    assert not lit.sees((100, 115))
    bare = _sight([_box(0, 0, 200, 100)], band=0)
    bare.reveal_from((100, 50))
    assert not bare.sees((100, 105))


def test_a_wall_thinner_than_the_band_does_not_light_the_room_behind_it():
    # Two rooms 6 px apart: the wall between them is lit right through, and no further.
    sight = _sight([_box(0, 0, 200, 300), _box(0, 100, 200, 106)], band=20)
    sight.reveal_from((100, 50))
    assert sight.sees((100, 104))
    assert not sight.sees((100, 110))


# ---------------------------------------------------------------- recasting

def test_a_small_step_keeps_the_fan_and_a_long_one_recasts():
    sight = _sight([_box(0, 0, 200, 100)])
    sight.reveal_from((50, 50))
    ring = sight.ring
    sight.reveal_from((53, 52))
    assert sight.ring is ring
    sight.reveal_from((60, 50))
    assert sight.ring is not ring


def test_hiding_drops_the_fan():
    sight = _sight([_box(0, 0, 200, 100)])
    sight.reveal_from((50, 50))
    sight.hide()
    assert not sight.active
    assert not sight.sees((50, 50))


def test_casting_against_four_hundred_walls_takes_a_few_milliseconds():
    """A guard against the cast sliding back to a Python loop, which takes ~1 s here."""
    rng = np.random.default_rng(0)
    # A hundred pillars over a 4000 px hall, every one in reach: 400 walls.
    walls = walls_from_loops([_box(x, y, x + 40, y + 40) for x, y in rng.uniform(0, 3960, (100, 2))])
    sight_ring((2000.0, 2000.0), walls, 3000.0, 8.0)
    start = time.perf_counter()
    for _ in range(10):
        sight_ring((2000.0, 2000.0), walls, 3000.0, 8.0)
    assert (time.perf_counter() - start) / 10 < 0.025


# ---------------------------------------------------------------- the building

def _building(sight_loops=None, sight_band=0.0, size=(400, 200)):
    _init()
    footprint = pygame.Rect((0, 0), size)
    mask = pygame.Mask(size, fill=True)
    roof = pygame.Surface(size, pygame.SRCALPHA)
    interior = pygame.Surface(size, pygame.SRCALPHA)
    return assemble(footprint, mask, roof, interior, chamber=(footprint, mask),
                    sight_loops=sight_loops, sight_band=sight_band)


def test_without_sight_walls_the_whole_chamber_shows():
    assert _building(sight_loops=None).sight is None


def test_with_sight_off_the_whole_chamber_shows(monkeypatch):
    monkeypatch.setattr(building_mod, "INTERIOR_SIGHT", False)
    assert _building(sight_loops=_TWO_ROOMS).sight is None


def test_walking_in_casts_from_the_feet_and_walking_out_drops_it():
    building = _building(sight_loops=_TWO_ROOMS, sight_band=4)
    building.update(0.016, (50, 100))
    assert building.inside
    assert building.sight.active
    assert building.sight.sees((300, 100))
    assert not building.sight.sees((350, 30))
    building.update(0.016, (900, 900))
    assert not building.inside
    assert not building.sight.active


# ---------------------------------------------------------------- drawing

class FakeGrassManager:
    def update_render(self, *args, **kwargs):
        return {}

    def apply_force(self, *args, **kwargs):
        return None


class RecordingBackend:
    def __init__(self, size=(400, 400)):
        self._size = size
        self.calls = []

    def get_size(self):
        return self._size

    def blit(self, surface, dest, *, flags=0, area=None, cache_key=None):
        self.calls.append(("blit", surface))

    def blit_fan(self, surface, dest, center, ring, *, cache_key=None):
        self.calls.append(("fan", surface))

    def invalidate_texture(self, surface):
        pass

    def fill(self, *a, **k):
        pass

    def draw_rect(self, *a, **k):
        pass

    def draw_circle(self, *a, **k):
        pass

    def draw_shadow(self, *a, **k):
        pass

    def draw_light(self, *a, **k):
        pass

    def draw_grass_instances(self, *a, **k):
        pass

    def build_grass_atlas(self, *a, **k):
        pass

    @property
    def grass_atlas_ready(self):
        return True

    @property
    def raw_surface(self):
        return pygame.Surface(self._size)


def _group(backend, building):
    group = YSortCameraGroup(
        pygame.sprite.Group(), FakeGrassManager(), [], backend=backend, buildings=[building])
    group.offset.update(0, 0)
    group.window_width, group.window_height = backend.get_size()
    return group


def _body(feet):
    body = pygame.sprite.Sprite()
    body.image = pygame.Surface((10, 20), pygame.SRCALPHA)
    body.rect = body.image.get_rect(midbottom=feet)
    body.hitbox = body.rect.copy()
    return body


def test_inside_the_chamber_is_black_and_the_interior_shows_through_the_fan():
    building = _building(sight_loops=_TWO_ROOMS)
    backend = RecordingBackend()
    group = _group(backend, building)
    group._draw_building_interiors()
    assert backend.calls == [], "outside: the roof is the building"

    building.update(0.016, (50, 100))
    group._draw_building_interiors()
    assert backend.calls == [("blit", building.sight.black), ("fan", building.interior)]


def test_a_building_without_sight_walls_draws_its_whole_interior_inside():
    building = _building(sight_loops=None)
    backend = RecordingBackend()
    group = _group(backend, building)
    building.update(0.016, (50, 100))
    group._draw_building_interiors()
    assert backend.calls == [("blit", building.interior)]


def test_bodies_whose_feet_are_out_of_sight_are_left_out():
    building = _building(sight_loops=_TWO_ROOMS)
    group = _group(RecordingBackend(), building)
    building.update(0.016, (50, 100))
    lit = group._lit_buildings()
    assert lit == [building]
    subject = _body((50, 100))
    assert not group._out_of_sight(_body((300, 100)), subject, lit), "through the doorway"
    assert group._out_of_sight(_body((350, 30)), subject, lit), "behind the partition"
    assert not group._out_of_sight(_body((450, 100)), subject, lit), "off the floor"
    unseen_subject = _body((350, 30))
    assert not group._out_of_sight(unseen_subject, unseen_subject, lit), "the subject is drawn"


def test_cpu_blit_fan_draws_only_inside_the_ring():
    _init()
    screen = pygame.Surface((40, 40), pygame.SRCALPHA)
    art = pygame.Surface((40, 40), pygame.SRCALPHA)
    art.fill((200, 50, 50, 255))
    CPUBackend(screen).blit_fan(art, (0, 0), (20, 20), _box(10, 10, 30, 30), cache_key=id(art))
    assert screen.get_at((20, 20)) == (200, 50, 50, 255)
    assert screen.get_at((5, 5))[3] == 0
    assert screen.get_at((35, 20))[3] == 0
