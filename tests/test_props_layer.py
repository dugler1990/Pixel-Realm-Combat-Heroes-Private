"""Props placed in Tiled: drawn depth-sorted, solid only where they stand.

A statue painted onto the ground layer can never be walked behind, and a whole-picture
obstacle stops you at its head. So the art joins the y-sorted sprites, and the obstacle is
only the bottom of the silhouette -- unless it hangs on a wall, where it blocks nothing.
"""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code"))

import pygame  # noqa: E402

from Support import prop_base_mask  # noqa: E402


def _solid(w, h):
    mask = pygame.Mask((w, h))
    mask.fill()
    return mask


def test_tall_prop_blocks_at_its_plinth():
    top, band = prop_base_mask(_solid(20, 60))
    assert (top, band.get_size(), band.count()) == (50, (20, 10), 200)


def test_low_wide_prop_blocks_over_its_whole_height():
    top, band = prop_base_mask(_solid(60, 24))
    assert (top, band.get_size()) == (0, (60, 24))


def test_base_follows_the_silhouette_not_the_image_box():
    mask = pygame.Mask((40, 80))
    for x in range(10, 30):  # opaque 20x50, ending 10 px above the image bottom
        for y in range(20, 70):
            mask.set_at((x, y))
    top, band = prop_base_mask(mask)
    assert top == 60 and band.get_size() == (40, 10)
    assert band.get_at((10, 0)) and not band.get_at((5, 0))


def test_empty_prop_has_no_base():
    assert prop_base_mask(pygame.Mask((8, 8))) is None


def _placed(x, y, w, h, **properties):
    image = pygame.Surface((w, h), pygame.SRCALPHA)
    image.fill((200, 150, 60, 255))
    return SimpleNamespace(image=image, x=x, y=y, width=w, height=h, name="", id=1,
                           properties=properties)


def _manager():
    pytest.importorskip("pytmx")
    from Settings import TILESIZE
    from tmx_layout_manager import LayoutManager

    manager = LayoutManager.__new__(LayoutManager)
    manager.tmxdata = SimpleNamespace(tilewidth=TILESIZE, tileheight=TILESIZE)  # 1:1 map scale
    manager.visible_sprites = pygame.sprite.Group()
    manager.obstacle_sprites = pygame.sprite.Group()
    return manager


def test_floor_prop_is_y_sorted_art_with_a_base_obstacle():
    manager = _manager()
    manager.create_props_layer([_placed(100, 200, 30, 90, mount="floor")])

    (art,) = manager.visible_sprites.sprites()
    (base,) = manager.obstacle_sprites.sprites()
    assert art.rect == pygame.Rect(100, 200, 30, 90)
    assert base.rect == pygame.Rect(100, 275, 30, 15)
    assert base.mask.get_size() == base.rect.size and base.mask.count() == 30 * 15


def test_wall_prop_blocks_nothing():
    manager = _manager()
    manager.create_props_layer([_placed(0, 0, 20, 60, mount="wall")])
    assert len(manager.visible_sprites) == 1 and len(manager.obstacle_sprites) == 0


def _furnished():
    """Two variants of one building's furnishing, and one prop placed by hand."""
    return [_placed(0, 0, 10, 20, building="pyramid", variant="v01"),
            _placed(50, 0, 10, 20, building="pyramid", variant="v01"),
            _placed(100, 0, 10, 20, building="pyramid", variant="v02"),
            _placed(200, 0, 10, 20)]


def test_one_furnishing_variant_per_building_is_loaded():
    for _ in range(8):
        manager = _manager()
        manager.create_props_layer(_furnished())
        xs = sorted(sprite.rect.x for sprite in manager.visible_sprites)
        assert xs in ([0, 50, 200], [100, 200]), "one variant, never both; the hand prop always"


def test_a_brazier_burns_like_a_torch_in_its_building():
    from Lighting import LightingManager

    manager = _manager()
    manager.lighting = LightingManager()
    manager.create_props_layer([_placed(100, 200, 30, 40, type="brazier", building="pyramid"),
                                _placed(0, 0, 20, 60, type="statue", building="pyramid")])
    (light,) = manager.lighting._registry
    assert (light.x, light.y, light.building) == (115, 220, "pyramid")
    assert light.radius == manager.lighting.torch_radius


def test_the_debug_setting_picks_the_variant(monkeypatch):
    import Settings

    monkeypatch.setattr(Settings, "DEBUG_PROPS_VARIANT", "v02")
    manager = _manager()
    manager.create_props_layer(_furnished())
    assert sorted(sprite.rect.x for sprite in manager.visible_sprites) == [100, 200]
