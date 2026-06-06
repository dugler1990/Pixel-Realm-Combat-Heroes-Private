import os

import pygame

PLACEHOLDER_SPECS = {
    "chief_eskimo": ((24, 32), (168, 216, 234, 255)),
    "chief_jungle": ((24, 32), (45, 106, 79, 255)),
    "worker_eskimo": ((16, 24), (204, 204, 204, 255)),
    "worker_jungle": ((16, 24), (149, 212, 74, 255)),
    "node_seal_hole": ((32, 32), (176, 224, 230, 255)),
    "node_seal_colony": ((32, 32), (176, 224, 230, 255)),
    "node_whale_shore": ((48, 32), (27, 58, 107, 255)),
    "node_whale": ((48, 32), (27, 58, 107, 255)),
    "node_ice_shelf": ((32, 32), (238, 238, 238, 255)),
    "node_walrus_shore": ((32, 32), (245, 222, 179, 255)),
    "node_polar_bear_den": ((32, 32), (245, 222, 179, 255)),
    "node_fruit_grove": ((32, 32), (255, 159, 28, 255)),
    "node_hardwood_tree": ((24, 40), (107, 66, 38, 255)),
    "node_clay_bank": ((32, 24), (193, 68, 14, 255)),
    "node_obsidian_outcrop": ((32, 32), (26, 26, 46, 255)),
    "node_spice_cluster": ((24, 24), (199, 125, 255, 255)),
    "building_smoking_rack": ((40, 40), (74, 144, 217, 255)),
    "building_hunters_lodge": ((40, 40), (74, 144, 217, 255)),
    "building_rendering_pit": ((40, 40), (44, 62, 122, 255)),
    "building_rendering_hut": ((40, 40), (44, 62, 122, 255)),
    "building_ice_cutting_post": ((40, 40), (112, 128, 144, 255)),
    "building_storage_hut": ((40, 40), (112, 128, 144, 255)),
    "building_carving_lodge": ((40, 40), (123, 45, 139, 255)),
    "building_village_hearth": ((40, 40), (224, 92, 42, 255)),
    "building_wood_store": ((40, 40), (78, 46, 14, 255)),
    "building_clay_works": ((40, 40), (160, 82, 45, 255)),
    "building_knapping_stone": ((40, 40), (51, 51, 51, 255)),
    "building_trade_hut": ((40, 40), (123, 45, 139, 255)),
}

_cache = {}


def _assets_dir():
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "Graphics", "rts_placeholders")
    )


def ensure_placeholder_files():
    folder = _assets_dir()
    os.makedirs(folder, exist_ok=True)
    for key, (size, color) in PLACEHOLDER_SPECS.items():
        path = os.path.join(folder, f"{key}.png")
        if not os.path.isfile(path):
            surf = pygame.Surface(size, pygame.SRCALPHA)
            surf.fill(color)
            pygame.image.save(surf, path)


def load_sprite(sprite_key, fallback_size=(32, 32), fallback_color=(200, 200, 200, 255)):
    key = str(sprite_key or "").strip()
    if not key:
        surf = pygame.Surface(fallback_size, pygame.SRCALPHA)
        surf.fill(fallback_color)
        return surf
    if key in _cache:
        return _cache[key]
    ensure_placeholder_files()
    path = os.path.join(_assets_dir(), f"{key}.png")
    if os.path.isfile(path):
        surf = pygame.image.load(path)
        try:
            surf = surf.convert_alpha()
        except pygame.error:
            pass
    elif key in PLACEHOLDER_SPECS:
        size, color = PLACEHOLDER_SPECS[key]
        surf = pygame.Surface(size, pygame.SRCALPHA)
        surf.fill(color)
    else:
        surf = pygame.Surface(fallback_size, pygame.SRCALPHA)
        surf.fill(fallback_color)
    _cache[key] = surf
    return surf


def sprite_footprint_size(sprite_key):
    key = str(sprite_key or "").strip()
    if key in PLACEHOLDER_SPECS:
        return PLACEHOLDER_SPECS[key][0]
    return (32, 32)


def normalize_faction_id(faction_id):
    fid = str(faction_id or "").strip().lower()
    if fid == "jungle":
        return "jungle_tribe"
    return fid
