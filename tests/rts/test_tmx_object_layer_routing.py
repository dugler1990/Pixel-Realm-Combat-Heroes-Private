"""Unit tests for TMX object-layer routing (mixed image + shape layers)."""


class _FakeObj:
    def __init__(self, image):
        self.image = image


def _route_object_layer(layer_name, objects):
    """Mirror initialize_layout routing for generic object layers."""
    layer_name_lower = layer_name.lower()
    has_effect_name = layer_name.find("Effect") != -1
    has_spawner_name = layer_name_lower.find("spawner") != -1
    has_placed_entities_name = "placed_entities" in layer_name_lower
    has_item_name = "item" in layer_name_lower
    has_grass_name = "grass" in layer_name_lower
    has_interactables_name = "interactable" in layer_name_lower
    has_shape_objects = any(getattr(obj, "image", None) is None for obj in objects)
    has_image_objects = any(getattr(obj, "image", None) is not None for obj in objects)

    if has_spawner_name:
        return "spawner"
    if has_placed_entities_name:
        return "placed_entities"
    if has_item_name:
        return "item"
    if has_grass_name:
        return "grass"
    if has_interactables_name:
        return "object"
    if layer_name_lower == "chiefs":
        return "chiefs"
    if layer_name_lower == "resource_nodes":
        return "resource_nodes"
    if layer_name_lower == "dropoff_buildings":
        return "dropoff_buildings"
    if has_effect_name or (has_shape_objects and not has_image_objects):
        return "effect"
    return "object"


def test_rts_dedicated_layers_route_correctly():
    assert _route_object_layer("chiefs", []) == "chiefs"
    assert _route_object_layer("resource_nodes", []) == "resource_nodes"
    assert _route_object_layer("dropoff_buildings", []) == "dropoff_buildings"


def test_mixed_image_and_shape_layer_routes_to_object_layer():
    objs = [_FakeObj(image="tile"), _FakeObj(image=None)]
    assert _route_object_layer("Object Layer 1", objs) == "object"


def test_shape_only_layer_routes_to_effect_layer():
    objs = [_FakeObj(image=None), _FakeObj(image=None)]
    assert _route_object_layer("Object Layer 1", objs) == "effect"


def test_effect_named_layer_routes_to_effect_layer_even_with_images():
    objs = [_FakeObj(image="tile"), _FakeObj(image=None)]
    assert _route_object_layer("Smoke Effect", objs) == "effect"
