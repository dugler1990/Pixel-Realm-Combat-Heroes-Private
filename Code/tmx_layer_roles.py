"""TMX object layer name → role dispatch for LayoutManager."""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

from game_logging import get_tmx_layout_logger

if TYPE_CHECKING:
    from tmx_layout_manager import LayoutManager

_log = get_tmx_layout_logger()


class LayerRole(str, Enum):
    PAINTED_GROUND = "painted_ground"
    BUILDINGS = "buildings"
    OBJECTS = "objects"
    EFFECT = "effect"
    SPAWNER = "spawner"
    GRASS_OBJECTS = "grass_objects"
    INTERACTABLES = "interactables"
    RTS_CHIEFS = "rts_chiefs"
    RTS_RESOURCE_NODES = "rts_resource_nodes"
    RTS_DROPOFF = "rts_dropoff"


# Exact Tiled objectgroup name → role (legacy names from existing maps included).
LAYER_ROLES: dict[str, LayerRole] = {
    "PaintedGround": LayerRole.PAINTED_GROUND,
    "Buildings": LayerRole.BUILDINGS,
    "Objects": LayerRole.OBJECTS,
    "ObstaclePolygons": LayerRole.OBJECTS,
    "PaintedCollision": LayerRole.OBJECTS,
    "Object Layer 1": LayerRole.OBJECTS,
    "Heat Effect Layer": LayerRole.EFFECT,
    "Slippery Effect Layer": LayerRole.EFFECT,
    "Slipery Layer": LayerRole.EFFECT,
    "spawner": LayerRole.SPAWNER,
    "grass1": LayerRole.GRASS_OBJECTS,
    "GrassObjects": LayerRole.GRASS_OBJECTS,
    "Interactables": LayerRole.INTERACTABLES,
    "chiefs": LayerRole.RTS_CHIEFS,
    "resource_nodes": LayerRole.RTS_RESOURCE_NODES,
    "rts_resource_nodes": LayerRole.RTS_RESOURCE_NODES,
    "dropoff_buildings": LayerRole.RTS_DROPOFF,
}


def resolve_layer_role(layer_name: str) -> LayerRole:
    if layer_name in LAYER_ROLES:
        return LAYER_ROLES[layer_name]
    if "Effect" in layer_name:
        return LayerRole.EFFECT
    _log.warning(
        "Unknown object layer %r — defaulting to objects role; add to LAYER_ROLES if intentional",
        layer_name,
    )
    return LayerRole.OBJECTS


def dispatch_object_layer(manager: LayoutManager, layer: Any, role: LayerRole) -> None:
    if role is LayerRole.PAINTED_GROUND:
        manager.create_painted_ground_layer(layer)
    elif role is LayerRole.BUILDINGS:
        manager.create_building_layer(layer)
    elif role is LayerRole.SPAWNER:
        if hasattr(manager, "spawner"):
            manager.create_spawner_layer(layer)
        else:
            _log.debug(
                "Warning: Spawner layer found but spawner not set. Skipping spawner processing.",
            )
    elif role is LayerRole.GRASS_OBJECTS:
        manager.create_grass_object_layer(layer)
    elif role is LayerRole.INTERACTABLES:
        manager.create_object_layer(layer)
    elif role is LayerRole.RTS_CHIEFS:
        from rts.tmx_spawn import spawn_chiefs_layer

        spawn_chiefs_layer(manager, layer)
    elif role is LayerRole.RTS_RESOURCE_NODES:
        from rts.tmx_spawn import spawn_resource_nodes_layer

        spawn_resource_nodes_layer(manager, layer)
    elif role is LayerRole.RTS_DROPOFF:
        from rts.tmx_spawn import spawn_dropoff_buildings_layer

        spawn_dropoff_buildings_layer(manager, layer)
    elif role is LayerRole.EFFECT:
        manager.create_effect_layer(layer)
    else:
        manager.create_object_layer(layer)
