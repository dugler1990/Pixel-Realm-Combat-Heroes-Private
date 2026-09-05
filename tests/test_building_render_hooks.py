"""Where the camera group draws buildings: full roof outside, chamber cutaway inside."""

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

import pygame  # noqa: E402

from Building import VIEW_DOOR, VIEW_IN, Building, arch_quad  # noqa: E402
from YsortCameraGroup import YSortCameraGroup  # noqa: E402


class FakeGrassManager:
    def update_render(self, *args, **kwargs):
        return {}

    def apply_force(self, *args, **kwargs):
        return None


class RecordingBackend:
    """Records blits instead of drawing, so we can assert on draw order."""

    def __init__(self, size=(200, 200)):
        self._size = size
        self.calls = []

    def get_size(self):
        return self._size

    def blit(self, surface, dest, *, flags=0, area=None, cache_key=None):
        self.calls.append((surface, dest))

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
    """Hitbox is the world-position authority; rect is deliberately elsewhere."""

    def __init__(self, feet):
        self.hitbox = pygame.Rect(0, 0, 10, 10)
        self.hitbox.midbottom = feet
        self.rect = pygame.Rect(0, 0, 10, 10)
        self.rect.midbottom = (feet[0] + 5000, feet[1] + 5000)


def _group(building):
    pygame.display.init()
    pygame.display.set_mode((200, 200))
    backend = RecordingBackend()
    group = YSortCameraGroup(
        pygame.sprite.Group(), FakeGrassManager(), [], backend=backend,
        buildings=[building],
    )
    group.offset.update(0, 0)
    group.window_width, group.window_height = 200, 200
    return group, backend


def _building(**kwargs):
    footprint = kwargs.pop("footprint", pygame.Rect(20, 20, 100, 80))
    roof = pygame.Surface(footprint.size, pygame.SRCALPHA)
    roof.fill((200, 160, 100, 255))
    interior = pygame.Surface(footprint.size, pygame.SRCALPHA)
    roof_open = kwargs.pop("roof_open", None)
    if roof_open is None:
        roof_open = roof.copy()
        roof_open.fill((0, 0, 0, 0))
        # Leave a 10px shell so the open roof is still a distinct surface with walls.
        pygame.draw.rect(roof_open, (200, 160, 100, 255), roof_open.get_rect(), 10)
    return Building(footprint, roof, interior, roof_open=roof_open, **kwargs)


def test_roof_is_intact_while_outside():
    b = _building()
    group, backend = _group(b)
    far = (5000, 5000)
    b.update(0.016, far)

    group._draw_building_roofs(Focus(far))

    assert len(backend.calls) == 1, "roof draws whenever on screen, unlike canopy"
    surface, dest = backend.calls[-1]
    assert surface is b.roof
    assert dest == (b.footprint.x, b.footprint.y)


def test_sprites_in_front_of_a_roof_are_redrawn_on_top():
    """Roofs draw after sprites; without a second pass the body vanishes in the door."""
    b = _building()
    group, backend = _group(b)
    sprite = pygame.sprite.Sprite()
    sprite.image = pygame.Surface((10, 20), pygame.SRCALPHA)
    sprite.rect = pygame.Rect(60, 70, 10, 20)
    sprite.hitbox = sprite.rect
    group.add(sprite)
    group._draw_building_roofs(Focus((65, 90)))
    surfaces = [c[0] for c in backend.calls]
    assert sprite.image in surfaces, "player in the doorway must draw over the roof"


def test_inside_blits_roof_open_not_the_full_roof():
    b = _building()
    group, backend = _group(b)
    b.update(0.016, b.footprint.center)

    group._draw_building_roofs(Focus(b.footprint.center))

    surface, dest = backend.calls[-1]
    assert surface is b.roof_open
    assert surface is not b.roof
    assert dest == (b.footprint.x, b.footprint.y)


def test_offscreen_building_is_culled():
    b = _building()
    group, backend = _group(b)
    group.offset.update(10000, 10000)

    group._draw_building_roofs(Focus((5000, 5000)))
    group._draw_building_interiors()

    assert backend.calls == []


def test_interior_is_skipped_until_inside_then_drawn_at_footprint():
    b = _building()
    group, backend = _group(b)

    group._draw_building_interiors()
    assert backend.calls == [], "nothing to draw with the roof intact"

    b.update(0.016, b.footprint.center)
    group._draw_building_interiors()
    assert len(backend.calls) == 1
    surface, dest = backend.calls[0]
    assert surface is b.interior
    assert dest == (b.footprint.x, b.footprint.y)


def test_update_probes_the_camera_subject_not_the_player():
    """Focus.rect is 5000px away; using it instead of the hitbox would miss."""
    b = _building()
    group, _backend = _group(b)

    group._update_buildings(Focus(b.footprint.center), 0.016)

    assert b.inside


def test_chamber_cutaway_still_draws_a_roof():
    """A smaller chamber opens the room; it does not hide the whole building."""
    footprint = pygame.Rect(20, 20, 100, 80)
    chamber = pygame.Rect(40, 40, 30, 30)
    roof = pygame.Surface(footprint.size, pygame.SRCALPHA)
    roof.fill((200, 160, 100, 255))
    roof_open = roof.copy()
    roof_open.fill((0, 0, 0, 0), (20, 20, 30, 30))  # punch chamber in local px
    b = Building(
        footprint, roof, pygame.Surface(footprint.size, pygame.SRCALPHA),
        chamber_rect=chamber, chamber_mask=pygame.Mask((30, 30), fill=True),
        roof_open=roof_open,
    )
    group, backend = _group(b)
    b.update(0.016, chamber.center)
    group._draw_building_roofs(Focus(chamber.center))
    surface, _dest = backend.calls[-1]
    assert surface is b.roof_open
    assert surface.get_at((0, 0))[3] == 255, "outer wall of the roof stays"
    assert surface.get_at((20, 20))[3] == 0, "chamber is punched"


class CompositingBackend(RecordingBackend):
    """Records blits and actually composites, for pixel checks in the doorway."""

    def __init__(self, size=(200, 200)):
        super().__init__(size)
        self._surface = pygame.Surface(size, pygame.SRCALPHA)
        self._surface.fill((0, 0, 0, 0))

    @property
    def raw_surface(self):
        return self._surface

    def blit(self, surface, dest, *, flags=0, area=None, cache_key=None):
        self.calls.append((surface, dest, surface.get_size()))
        if area is not None:
            self._surface.blit(surface, dest, area=area, special_flags=flags)
        else:
            self._surface.blit(surface, dest, special_flags=flags)


def _south_door_render_building():
    """80x80, door on south, chamber y in [0, 61), door_depth 20. Distinct colours."""
    footprint = pygame.Rect(0, 0, 80, 80)
    origin = (40.0, 80.0)
    inward = (0.0, -1.0)
    tangent = (1.0, 0.0)
    door_depth = 20.0
    chamber = pygame.Rect(10, 0, 60, 61)
    roof = pygame.Surface(footprint.size, pygame.SRCALPHA)
    roof.fill((200, 100, 50, 255))
    interior = pygame.Surface(footprint.size, pygame.SRCALPHA)
    interior.fill((30, 80, 180, 255))
    roof_open = roof.copy()
    # Chamber in local px: (10, 0, 60, 61)
    roof_open.fill((0, 0, 0, 0), chamber)
    return Building(
        footprint, roof, interior,
        chamber_rect=chamber, chamber_mask=pygame.Mask(chamber.size, fill=True),
        roof_open=roof_open,
        door_origin=origin, door_inward=inward, door_depth=door_depth,
        arch_quad=arch_quad(origin, inward, tangent, 40, door_depth),
        door_lip_jitter=8,
    )


def test_door_split_far_arch_is_interior_near_is_roof():
    b = _south_door_render_building()
    pygame.display.init()
    pygame.display.set_mode((80, 80))
    backend = CompositingBackend(size=(80, 80))
    group = YSortCameraGroup(
        pygame.sprite.Group(), FakeGrassManager(), [], backend=backend, buildings=[b])
    group.offset.update(0, 0)
    group.window_width, group.window_height = 80, 80

    b.update(0.016, (40, 70))  # depth 10, in the arch
    assert b.view == VIEW_DOOR
    group._draw_building_interiors()
    group._draw_building_roofs(Focus((40, 70)))

    far = backend.raw_surface.get_at((40, 65))   # depth 15, far
    near = backend.raw_surface.get_at((40, 75))  # depth 5, near
    assert far[:3] == (30, 80, 180), "far arch must show interior"
    assert near[:3] == (200, 100, 50), "near arch must stay roof"
    inner = backend.raw_surface.get_at((40, 40))  # chamber, far, in-composite
    assert inner[:3] == (30, 80, 180)
    patch_sizes = [c[2] for c in backend.calls if c[2] != b.footprint.size]
    assert patch_sizes, "door state must blit a small arch patch"
    pw, ph = patch_sizes[-1]
    assert pw * ph < b.footprint.w * b.footprint.h, "patch is not the full footprint"


def test_door_inner_edge_matches_in_composite():
    b = _south_door_render_building()
    pygame.display.init()
    pygame.display.set_mode((80, 80))

    def _draw(feet):
        backend = CompositingBackend(size=(80, 80))
        group = YSortCameraGroup(
            pygame.sprite.Group(), FakeGrassManager(), [], backend=backend, buildings=[b])
        group.offset.update(0, 0)
        group.window_width, group.window_height = 80, 80
        b.update(0.016, feet)
        group._draw_building_interiors()
        group._draw_building_roofs(Focus(feet))
        return backend.raw_surface, b.view

    in_surf, in_view = _draw((40, 30))
    assert in_view == VIEW_IN
    door_surf, door_view = _draw((40, 70))
    assert door_view == VIEW_DOOR
    # Chamber pixel: far during door, same as fully in.
    assert door_surf.get_at((40, 40))[:3] == in_surf.get_at((40, 40))[:3]


def test_player_is_redrawn_on_top_in_door_view():
    b = _south_door_render_building()
    group, backend = _group(b)
    b.update(0.016, (40, 70))
    sprite = pygame.sprite.Sprite()
    sprite.image = pygame.Surface((10, 20), pygame.SRCALPHA)
    sprite.rect = pygame.Rect(35, 55, 10, 20)
    sprite.hitbox = sprite.rect
    group.add(sprite)
    group._draw_building_roofs(Focus((40, 70)))
    assert backend.calls[-1][0] is sprite.image


def test_interior_is_drawn_in_door_view():
    b = _south_door_render_building()
    group, backend = _group(b)
    b.update(0.016, (40, 70))
    group._draw_building_interiors()
    assert any(c[0] is b.interior for c in backend.calls)
