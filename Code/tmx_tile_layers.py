"""Shared pytmx tile-layer helpers (correct layer index for get_tile_* calls)."""

_PYTMX_IMAGE_META_KEYS = frozenset({"id", "source", "trans", "width", "height", "frames"})


def layer_index(tmxdata, layer):
    """Index of layer in tmxdata.layers (not Tiled layer id)."""
    for idx, lyr in enumerate(tmxdata.layers):
        if lyr is layer:
            return idx
    return 0


def _overlay_custom_props(merged, extra):
    if not extra:
        return
    for key, value in extra.items():
        if key in _PYTMX_IMAGE_META_KEYS:
            continue
        merged[key] = value


def tile_properties(tmxdata, layer, tx, ty):
    idx = layer_index(tmxdata, layer)
    gid = tile_gid(tmxdata, layer, tx, ty)
    if not gid:
        return {}

    merged = {}
    try:
        tileset = tmxdata.get_tileset_from_gid(gid)
        merged.update(dict(getattr(tileset, "properties", {}) or {}))
    except (ValueError, KeyError, AttributeError):
        pass

    _overlay_custom_props(merged, tmxdata.get_tile_properties_by_gid(gid))
    try:
        raw = tmxdata.get_tile_properties(tx, ty, idx)
        _overlay_custom_props(merged, raw)
    except Exception:
        pass
    return merged


def tile_gid(tmxdata, layer, tx, ty):
    idx = layer_index(tmxdata, layer)
    return tmxdata.get_tile_gid(tx, ty, idx)


def tile_surface(tmxdata, layer, tx, ty):
    idx = layer_index(tmxdata, layer)
    return tmxdata.get_tile_image(tx, ty, idx)
