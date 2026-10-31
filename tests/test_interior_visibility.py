"""Fog of war inside a building: the floor you have walked near shows, the rest is black."""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Code"))

import Building as building_mod  # noqa: E402
from Building import assemble  # noqa: E402
from interior_visibility import InteriorFog, floor_cells  # noqa: E402
from render_backend import CPUBackend  # noqa: E402
from YsortCameraGroup import YSortCameraGroup  # noqa: E402


@pytest.fixture(autouse=True)
def _fog_on(monkeypatch):
    monkeypatch.setattr(building_mod, "INTERIOR_FOG", True)


def _init():
    pygame.display.init()
    pygame.display.set_mode((64, 64))


def _hall():
    """A 400 x 300 floor split by a 40 px wall at x 180..220 that stops 40 px short of
    the bottom: two rooms that join only along the bottom."""
    _init()
    mask = pygame.Mask((400, 300), fill=True)
    mask.erase(pygame.Mask((40, 260), fill=True), (180, 0))
    return pygame.Rect(0, 0, 400, 300), mask


def _fog(radius=150):
    rect, mask = _hall()
    return InteriorFog(rect, mask, cell=10, radius=radius)


# ---------------------------------------------------------------- what is explored

def test_a_cell_holding_any_floor_is_floor():
    _init()
    mask = pygame.Mask((20, 10))
    mask.set_at((19, 9))
    assert floor_cells(pygame.Rect(0, 0, 20, 10), mask, cell=10).tolist() == [[False, True]]


def test_exploring_shows_the_floor_round_your_feet():
    fog = _fog()
    fog.explore_from((100, 100))
    assert fog.explored_at((100, 100))
    assert fog.explored_at((40, 100)), "60 px away"
    assert fog.explored_at((100, 220)), "120 px away"
    assert not fog.explored_at((100, 280)), "180 px away, past the reach"


def test_exploring_never_shows_a_room_through_a_wall():
    fog = _fog()
    fog.explore_from((170, 30))
    assert fog.explored_at((150, 30))
    assert not fog.explored_at((230, 30)), "60 px away in a straight line, 500 walking"


def test_through_the_gap_as_far_as_you_could_walk():
    fog = _fog()
    fog.explore_from((200, 280))
    assert fog.explored_at((160, 280)) and fog.explored_at((240, 280)), "both rooms at the gap"
    assert not fog.explored_at((240, 100)), "but no further than the reach"


def _fog_with_walls(radius=150):
    rect, mask = _hall()
    walls = pygame.Mask(rect.size)
    walls.draw(pygame.Mask((40, 260), fill=True), (180, 0))  # the wall between the rooms
    return InteriorFog(rect, mask, walls, cell=10, radius=radius)


def test_the_wall_beside_explored_floor_shows_but_never_the_room_behind_it():
    fog = _fog_with_walls()
    assert fog.surface.get_at((20, 3))[3] == 255, "an unexplored wall is fogged"
    fog.explore_from((170, 30))
    assert fog.explored_at((200, 30)), "the wall beside you"
    assert fog.surface.get_at((20, 3))[3] == 0
    assert not fog.explored_at((230, 30)), "the room behind it"
    assert fog.surface.get_at((23, 3))[3] == 255


def test_the_fog_is_clear_where_explored_and_says_it_changed():
    fog = _fog()
    assert not fog.changed
    fog.explore_from((100, 100))
    assert fog.changed
    assert fog.surface.get_at((10, 10))[3] == 0, "the cell under the feet"
    assert fog.surface.get_at((35, 3))[3] == 255, "the far room"


def test_the_fog_darkens_unexplored_floor_and_a_cell_round_it_nothing_else():
    """The chamber's box is bigger than its floor -- on the pyramid it reaches over the sand
    past the sloping walls -- and fog over the sand blacked out a rectangle of desert."""
    _init()
    mask = pygame.Mask((100, 100))
    mask.draw(pygame.Mask((50, 100), fill=True), (0, 0))  # the left half is floor
    fog = InteriorFog(pygame.Rect(0, 0, 100, 100), mask, cell=10, radius=30)
    assert fog.surface.get_at((2, 5))[3] == 255, "unexplored floor"
    assert fog.surface.get_at((5, 5))[3] == 255, "the ring round it"
    assert fog.surface.get_at((8, 5))[3] == 0, "past the ring"


# ---------------------------------------------------------------- the building

def _building(radius=150):
    rect, mask = _hall()
    roof = pygame.Surface(rect.size, pygame.SRCALPHA)
    interior = pygame.Surface(rect.size, pygame.SRCALPHA)
    building = assemble(rect, mask, roof, interior, chamber=(rect, mask))
    building.fog = InteriorFog(rect, mask, cell=10, radius=radius)
    return building


def test_without_fog_the_whole_floor_shows(monkeypatch):
    monkeypatch.setattr(building_mod, "INTERIOR_FOG", False)
    rect, mask = _hall()
    surface = pygame.Surface(rect.size, pygame.SRCALPHA)
    assert assemble(rect, mask, surface, surface, chamber=(rect, mask)).fog is None


def test_explored_floor_stays_explored_after_you_leave():
    building = _building()
    building.update(0.016, (100, 100))
    assert building.inside and building.fog.explored_at((100, 100))
    building.update(0.016, (900, 900))
    assert not building.inside
    assert building.fog.explored_at((100, 100))
    building.update(0.016, (300, 30))
    assert building.fog.explored_at((100, 100)) and building.fog.explored_at((300, 30))


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
        self.invalidated = []

    def get_size(self):
        return self._size

    def blit(self, surface, dest, *, flags=0, area=None, cache_key=None):
        self.calls.append(("blit", surface))

    def blit_scaled(self, surface, dest_rect, *, cache_key=None):
        self.calls.append(("scaled", surface))

    def invalidate_texture(self, surface):
        self.invalidated.append(surface)

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


def test_inside_the_building_is_black_then_floor_then_fog():
    building = _building()
    backend = RecordingBackend()
    group = _group(backend, building)
    group._draw_building_interiors()
    assert backend.calls == [], "outside: the roof is the building"

    building.update(0.016, (100, 100))
    group._draw_building_interiors()
    assert backend.calls == [("blit", building.black), ("blit", building.interior),
                             ("scaled", building.fog.surface)]
    assert backend.invalidated == [building.fog.surface], "explored floor: upload the fog again"
    assert not building.fog.changed

    group._draw_building_interiors()
    assert backend.invalidated == [building.fog.surface], "nothing new: no upload"


def test_bodies_standing_in_the_fog_are_left_out():
    building = _building()
    group = _group(RecordingBackend(), building)
    building.update(0.016, (100, 100))
    fogged = group._fogged_buildings()
    assert fogged == [building]
    subject = _body((100, 100))
    assert not group._in_fog(_body((100, 150)), subject, fogged), "on explored floor"
    assert group._in_fog(_body((300, 30)), subject, fogged), "in the room not yet explored"
    assert not group._in_fog(_body((450, 100)), subject, fogged), "off the floor"
    unexplored_subject = _body((300, 30))
    assert not group._in_fog(unexplored_subject, unexplored_subject, fogged), "the subject is drawn"


def test_cpu_blit_scaled_stretches_smoothly():
    _init()
    screen = pygame.Surface((40, 20), pygame.SRCALPHA)
    fog = pygame.Surface((2, 1), pygame.SRCALPHA)
    fog.fill((0, 0, 0, 255), (0, 0, 1, 1))
    CPUBackend(screen).blit_scaled(fog, (0, 0, 40, 20), cache_key=id(fog))
    assert screen.get_at((1, 10))[3] > 230, "the opaque cell"
    assert screen.get_at((38, 10))[3] < 25, "the clear cell"
    assert 0 < screen.get_at((20, 10))[3] < 255, "a soft edge between them"
