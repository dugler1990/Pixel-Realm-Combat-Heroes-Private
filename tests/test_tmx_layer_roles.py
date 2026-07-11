"""Tests for TMX layer role dispatch."""

from tmx_layer_roles import LAYER_ROLES, LayerRole, resolve_layer_role


def test_known_layers_resolve():
    assert resolve_layer_role("PaintedGround") is LayerRole.PAINTED_GROUND
    assert resolve_layer_role("Objects") is LayerRole.OBJECTS
    assert resolve_layer_role("ObstaclePolygons") is LayerRole.OBJECTS
    assert resolve_layer_role("Object Layer 1") is LayerRole.OBJECTS
    assert resolve_layer_role("Heat Effect Layer") is LayerRole.EFFECT
    assert resolve_layer_role("Slipery Layer") is LayerRole.EFFECT
    assert resolve_layer_role("spawner") is LayerRole.SPAWNER


def test_effect_substring_fallback():
    assert resolve_layer_role("Custom Effect Zone") is LayerRole.EFFECT


def test_interactables_not_item_layer():
    assert "Interactables" in LAYER_ROLES
    assert resolve_layer_role("Interactables") is LayerRole.INTERACTABLES
