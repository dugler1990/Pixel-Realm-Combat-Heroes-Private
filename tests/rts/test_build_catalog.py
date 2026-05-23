from rts.build.catalog import get_building, load_buildings


def test_ice_cutting_post_zero_cost_requires_deep_snow():
    building = get_building("ice_cutting_post")
    assert building is not None
    assert building.label == "Ice Cutting Post"
    assert building.cost == {}
    assert building.placement_requires == "deep_snow"
    assert building.spawn_dropoff_kind == "ice_cutting_post"
    assert building.spawn_node_kind == "ice_shelf"
    assert building.matches_faction("eskimo")


def test_buildings_cache_loads_json():
    buildings = load_buildings()
    assert "ice_cutting_post" in buildings
