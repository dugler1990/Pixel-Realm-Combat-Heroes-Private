"""Spawn RTS entities from Tiled object layers."""

from Settings import TILESIZE

from .assets import normalize_faction_id
from .entities import ChiefNPC, DropoffBuilding, ResourceNode


def _props_dict(obj):
    raw = getattr(obj, "properties", None) or {}
    return dict(raw) if raw else {}


def _center_pos(object_, x_pos, y_pos, w_scale, h_scale, tilesize=TILESIZE):
    gw = float(getattr(object_, "width", 0) or 0) * w_scale
    gh = float(getattr(object_, "height", 0) or 0) * h_scale
    if gw <= 0:
        gw = tilesize
    if gh <= 0:
        gh = tilesize
    return (x_pos + gw / 2, y_pos + gh / 2), gw, gh


def _object_center(layout_manager, object_):
    tiled_w = layout_manager.tmxdata.tilewidth
    tiled_h = layout_manager.tmxdata.tileheight
    x_pos = (object_.x * TILESIZE) / tiled_w
    y_pos = (object_.y * TILESIZE) / tiled_h
    w_scale = TILESIZE / tiled_w
    h_scale = TILESIZE / tiled_h
    center, _, _ = _center_pos(object_, x_pos, y_pos, w_scale, h_scale, TILESIZE)
    return center


def spawn_chiefs_layer(layout_manager, tmx_object_layer):
    registry = layout_manager.rts_registry
    groups = [layout_manager.obstacle_sprites, layout_manager.visible_sprites]
    for idx, object_ in enumerate(tmx_object_layer):
        props = _props_dict(object_)
        if str(props.get("rts_type", props.get("type", ""))).strip().lower() != "chief":
            continue
        center = _object_center(layout_manager, object_)
        config = dict(props)
        config["chief_id"] = f"chief_{props.get('faction_id', idx)}"
        chief = ChiefNPC(center, groups, config, registry)
        layout_manager.environment_interactables.append(chief)


def spawn_resource_nodes_layer(layout_manager, tmx_object_layer):
    registry = layout_manager.rts_registry
    groups = [layout_manager.obstacle_sprites, layout_manager.visible_sprites]
    env = layout_manager.environment_interactables
    spawned = 0
    for object_ in tmx_object_layer:
        props = _props_dict(object_)
        if str(props.get("rts_type", props.get("type", ""))).strip().lower() != "resource_node":
            continue
        center = _object_center(layout_manager, object_)
        node = ResourceNode(center, groups, props, registry)
        env.append(node)
        spawned += 1


def spawn_dropoff_buildings_layer(layout_manager, tmx_object_layer):
    registry = layout_manager.rts_registry
    groups = [layout_manager.obstacle_sprites, layout_manager.visible_sprites]
    env = layout_manager.environment_interactables
    for object_ in tmx_object_layer:
        props = _props_dict(object_)
        if str(props.get("rts_type", props.get("type", ""))).strip().lower() != "dropoff_building":
            continue
        center = _object_center(layout_manager, object_)
        building = DropoffBuilding(center, groups, props, registry)
        env.append(building)
