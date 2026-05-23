import pygame

from rts.build.sites_from_tiles import (
    _flood_fill_regions,
    _is_deep_snow_tile,
    _region_rect,
)
from Settings import TILESIZE


def test_deep_snow_tile_property_variants():
    assert _is_deep_snow_tile({"deep_snow": "true"})
    assert _is_deep_snow_tile({"rts_terrain": "deep_snow"})
    assert not _is_deep_snow_tile({})
    assert not _is_deep_snow_tile({"rts_terrain": "grass"})


def test_flood_fill_merges_connected_tiles():
    cells = {
        (0, 0): "eskimo",
        (1, 0): "eskimo",
        (0, 1): "eskimo",
        (5, 5): "eskimo",
    }
    regions = _flood_fill_regions(cells)
    assert len(regions) == 2
    sizes = sorted(len(r) for r in regions)
    assert sizes == [1, 3]


def test_region_rect_from_tile_component():
    component = [(2, 3), (3, 3), (2, 4)]
    rect = _region_rect(component)
    assert rect.left == 2 * TILESIZE
    assert rect.top == 3 * TILESIZE
    assert rect.width == 2 * TILESIZE
    assert rect.height == 2 * TILESIZE
