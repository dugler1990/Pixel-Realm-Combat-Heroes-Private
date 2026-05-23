import os

from pytmx import TiledMap

from rts.build.sites_from_tiles import deep_snow_cell_from_props
from tmx_tile_layers import tile_properties


def _load_map():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return TiledMap(os.path.join(root, "levels", "tmx", "map.tmx"))


def test_can_build_layer_cell_merges_tileset_deep_snow():
    tmx = _load_map()
    layer = next(lyr for lyr in tmx.layers if getattr(lyr, "name", "") == "can_build_layer")
    props = tile_properties(tmx, layer, 5, 5)
    assert props.get("deep_snow") == "true"


def test_can_build_layer_cell_registers_as_deep_snow_faction():
    tmx = _load_map()
    layer = next(lyr for lyr in tmx.layers if getattr(lyr, "name", "") == "can_build_layer")
    props = tile_properties(tmx, layer, 12, 17)
    assert deep_snow_cell_from_props(props) == "eskimo"
