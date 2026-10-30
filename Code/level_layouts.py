"""Level number <-> layout folder: the one table the client, the server and the tools read.

Paths are relative to Code/ (the game and the server both run from there). Adding a level
is one `level_N_layout_path` line and one `LAYOUT_TO_LEVEL` entry, which
tools/painted_map_pipeline/world_levels/register_level.py writes.
"""

level_6_layout_path = '../levels/tmx'
level_7_layout_path = '../levels/Map7'
level_8_layout_path = '../levels/Map8'
level_9_layout_path = '../levels/Frostreach/ice_wall_gate'
level_10_layout_path = '../levels/Frostreach/expanse'
level_11_layout_path = '../levels/Frostreach/sunspine_dunes_01'
level_12_layout_path = '../levels/Frostreach/sunspine_7x6_play'

LAYOUT_TO_LEVEL = {
    level_6_layout_path: 6,
    level_7_layout_path: 7,
    level_8_layout_path: 8,
    level_9_layout_path: 9,
    level_10_layout_path: 10,
    level_11_layout_path: 11,
    level_12_layout_path: 12,
}

# Inverted so a level number resolves to its folder in one lookup.
LEVEL_TO_LAYOUT = {number: path for path, number in LAYOUT_TO_LEVEL.items()}

# Where an unknown level number goes.
DEFAULT_LAYOUT = level_10_layout_path

# The co-op level the multiplayer client and server load.
MP_LEVEL_NUMBER = 6
