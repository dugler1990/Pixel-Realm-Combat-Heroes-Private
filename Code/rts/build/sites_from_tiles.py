"""Register build sites from deep_snow tile cells collected during layout load."""

import pygame

from Settings import TILESIZE

from ..assets import normalize_faction_id
from .site import BuildSite


def _truthy(val):
    if val is None:
        return False
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def is_deep_snow_tile(props):
    if not props:
        return False
    if _truthy(props.get("deep_snow")):
        return True
    if str(props.get("rts_terrain", "")).strip().lower() == "deep_snow":
        return True
    return False


def faction_from_tile_props(props):
    raw = props.get("build_faction") or props.get("faction_id") or "eskimo"
    return normalize_faction_id(raw)


def deep_snow_cell_from_props(props):
    if not is_deep_snow_tile(props):
        return None
    return faction_from_tile_props(props)


def _flood_fill_regions(cells):
    remaining = set(cells.keys())
    regions = []
    while remaining:
        start = remaining.pop()
        stack = [start]
        component = [start]
        while stack:
            x, y = stack.pop()
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) in remaining:
                    remaining.remove((nx, ny))
                    stack.append((nx, ny))
                    component.append((nx, ny))
        regions.append(component)
    return regions


def _region_rect(component):
    xs = [c[0] for c in component]
    ys = [c[1] for c in component]
    left = min(xs) * TILESIZE
    top = min(ys) * TILESIZE
    right = (max(xs) + 1) * TILESIZE
    bottom = (max(ys) + 1) * TILESIZE
    return pygame.Rect(left, top, right - left, bottom - top)


def register_build_sites_from_cells(layout_manager, cells):
    """Flood-fill deep_snow cells and register BuildSite regions."""
    if not cells:
        return 0
    registry = layout_manager.rts_registry
    groups = [layout_manager.obstacle_sprites, layout_manager.visible_sprites]
    env = layout_manager.environment_interactables
    count = 0
    site_idx = 0
    for component in _flood_fill_regions(cells):
        fid = cells[component[0]]
        rect = _region_rect(component)
        site = BuildSite(
            rect,
            fid,
            requires="deep_snow",
            site_id=f"site_{site_idx}",
            groups=groups,
        )
        site_idx += 1
        env.append(site)
        registry.register_build_site(site)
        count += 1
    return count
