"""Interior sight: walls block, unseen floor is black."""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Code"))

from Building import assemble  # noqa: E402
from interior_visibility import (  # noqa: E402
    InteriorSight,
    has_line_of_sight,
    rasterize_chamber,
    visible_cells,
)
from YsortCameraGroup import YSortCameraGroup  # noqa: E402


CELL = 8


def _init():
    pygame.display.init()
    pygame.display.set_mode((64, 64))


def _l_chamber(cell=CELL):
    """L: a 2-cell-wide vertical arm and a 2-cell-wide floor arm.

    ######
    ##
    ##
    ##
    ########
    ########
    """
    w = h = 8 * cell
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.rect(surf, (255, 255, 255, 255), (0, 0, 2 * cell, 8 * cell))
    pygame.draw.rect(surf, (255, 255, 255, 255), (0, 6 * cell, 8 * cell, 2 * cell))
    rect = pygame.Rect(0, 0, w, h)
    return rect, pygame.mask.from_surface(surf)


def test_open_rectangle_sees_itself():
    walkable = [[True, True], [True, True]]
    assert has_line_of_sight(walkable, 0, 0, 1, 1)
    assert visible_cells(walkable, (0, 0), 4) == {(0, 0), (1, 0), (0, 1), (1, 1)}


def test_a_wall_blocks_the_far_side():
    # Floor, wall, floor in a row.
    walkable = [[True, False, True]]
    assert has_line_of_sight(walkable, 0, 0, 0, 0)
    assert not has_line_of_sight(walkable, 0, 0, 2, 0)


def test_cannot_see_around_an_L_corner():
    _init()
    rect, mask = _l_chamber()
    walkable = rasterize_chamber(rect, mask, CELL)
    # Top of the vertical arm cannot see the far end of the floor arm.
    assert walkable[0][0] and walkable[7][7]
    assert not has_line_of_sight(walkable, 0, 0, 7, 7)
    seen = visible_cells(walkable, (0, 0), 20)
    assert (0, 0) in seen
    assert (0, 7) in seen, "the arm you stand in is visible"
    assert (7, 7) not in seen, "around the corner is not"


def test_the_corner_of_the_L_sees_both_arms():
    _init()
    rect, mask = _l_chamber()
    walkable = rasterize_chamber(rect, mask, CELL)
    seen = visible_cells(walkable, (1, 6), 20)
    assert (0, 0) in seen
    assert (7, 7) in seen


def test_reveal_from_blacks_out_the_unseen_arm():
    _init()
    rect, mask = _l_chamber()
    sight = InteriorSight(rect, mask, cell=CELL, radius=200)
    # Centre of the top-left cell.
    sight.reveal_from((CELL // 2, CELL // 2))
    assert sight.sees((CELL // 2, CELL // 2))
    assert sight.sees((CELL // 2, 7 * CELL + CELL // 2)), "same corridor"
    assert not sight.sees((7 * CELL + CELL // 2, 7 * CELL + CELL // 2))
    assert sight.active
    # Unseen cell is opaque black on the fog surface.
    fog_px = sight.fog.get_at((7 * CELL + CELL // 2, 7 * CELL + CELL // 2))
    assert fog_px[3] == 255 and fog_px[:3] == (0, 0, 0)
    visible_px = sight.fog.get_at((CELL // 2, CELL // 2))
    assert visible_px[3] == 0


def test_radius_hides_floor_that_is_in_line_but_too_far():
    _init()
    rect = pygame.Rect(0, 0, 16 * CELL, CELL)
    mask = pygame.Mask(rect.size, fill=True)
    sight = InteriorSight(rect, mask, cell=CELL, radius=3 * CELL)
    sight.reveal_from((CELL // 2, CELL // 2))
    assert sight.sees((CELL // 2, CELL // 2))
    assert not sight.sees((15 * CELL + CELL // 2, CELL // 2))


def test_stepping_within_a_cell_does_not_rebuild():
    _init()
    rect, mask = _l_chamber()
    sight = InteriorSight(rect, mask, cell=CELL, radius=200)
    sight.reveal_from((CELL // 2, CELL // 2))
    sight.consume_dirty()
    sight.reveal_from((CELL // 2 + 1, CELL // 2 + 1))
    assert not sight.consume_dirty()


def test_assemble_attaches_sight_to_a_chambered_building():
    _init()
    footprint = pygame.Rect(0, 0, 80, 80)
    mask = pygame.Mask((80, 80), fill=True)
    roof = pygame.Surface((80, 80), pygame.SRCALPHA)
    roof.fill((200, 160, 100, 255))
    interior = pygame.Surface((80, 80), pygame.SRCALPHA)
    interior.fill((30, 80, 180, 255))
    chamber = (pygame.Rect(20, 20, 30, 30), pygame.Mask((30, 30), fill=True))
    building = assemble(footprint, mask, roof, interior, chamber=chamber)
    assert building.sight is not None
    building.update(0.016, (35, 35))
    assert building.inside
    assert building.sight.visible


class FakeGrassManager:
    def update_render(self, *args, **kwargs):
        return {}

    def apply_force(self, *args, **kwargs):
        return None


class RecordingBackend:
    def __init__(self, size=(200, 200)):
        self._size = size
        self.calls = []
        self.invalidated = []

    def get_size(self):
        return self._size

    def blit(self, surface, dest, *, flags=0, area=None, cache_key=None):
        self.calls.append((surface, dest))

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


class Focus:
    def __init__(self, feet):
        self.hitbox = pygame.Rect(0, 0, 10, 10)
        self.hitbox.midbottom = feet
        self.rect = pygame.Rect(0, 0, 10, 10)
        self.rect.midbottom = feet


def test_fog_draws_after_sprites_and_only_when_inside():
    _init()
    rect, mask = _l_chamber()
    footprint = pygame.Rect(0, 0, rect.w, rect.h)
    roof = pygame.Surface(footprint.size, pygame.SRCALPHA)
    interior = pygame.Surface(footprint.size, pygame.SRCALPHA)
    building = assemble(
        footprint, pygame.Mask(footprint.size, fill=True), roof, interior,
        chamber=(rect, mask),
    )
    building.sight = InteriorSight(rect, mask, cell=CELL, radius=200)

    backend = RecordingBackend(size=(200, 200))
    group = YSortCameraGroup(
        pygame.sprite.Group(), FakeGrassManager(), [], backend=backend,
        buildings=[building],
    )
    group.offset.update(0, 0)
    group.window_width, group.window_height = 200, 200

    group._draw_interior_fog()
    assert backend.calls == [], "outside: no fog"

    feet = (CELL // 2, CELL // 2)
    building.update(0.016, feet)
    assert building.inside
    sprite = pygame.sprite.Sprite()
    sprite.image = pygame.Surface((4, 4), pygame.SRCALPHA)
    sprite.rect = pygame.Rect(2, 2, 4, 4)
    sprite.hitbox = sprite.rect
    group.add(sprite)

    group._draw_building_interiors()
    group._draw_sorted_sprite(sprite, sprite.rect.topleft)
    group._draw_interior_fog()
    group._draw_building_roofs(Focus(feet))
    surfaces = [c[0] for c in backend.calls]
    assert building.interior in surfaces
    assert building.sight.fog in surfaces
    assert surfaces.index(sprite.image) < surfaces.index(building.sight.fog)
    assert surfaces.index(building.sight.fog) < surfaces.index(building.roof_open)
    assert building.sight.fog in backend.invalidated
