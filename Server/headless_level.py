"""Build the REAL Level4 headless (server-side) -- no window, no rendering.

This is the foundation of the server-authoritative pivot (plan:
.claude/plans/ok-lets-make-a-drifting-yeti.md). The server runs the SAME Level4
the client runs, minus rendering: it constructs Level4 with a no-op StubBackend
under the dummy SDL driver, so the real Spawner / CombatUnit / Interaction sim
runs centrally with zero divergence from singleplayer.

Slice 1 only stands this up and proves it ticks like singleplayer (the real
spawner spawns real enemies headless). The GameServer (_step_world_sim) drives
this level's sim-only run() each tick and broadcasts the world to clients.
"""

import os
import sys

# Headless: no real window/audio device. Set before importing pygame.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_CODE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Code")
)
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)

import pygame  # noqa: E402

# Importing Level4_tmxdev pulls combat_unit, which chdir's to Code/ on import so
# the level's "../levels/..." + "../Graphics/..." asset paths resolve regardless
# of where the server process was launched from.
from Level4_tmxdev import Level4  # noqa: E402
from inputManager import InputManager  # noqa: E402
from game_settings import GameSettings  # noqa: E402
from PlayerSelection import (  # noqa: E402
    unlocked_player_base_stats,
    unlocked_player_directory,
)
from render_backend import StubBackend  # noqa: E402

# Layout dirs are relative to Code/ (combat_unit chdir'd us there on import).
_LEVEL_LAYOUTS = {
    6: "../levels/tmx",
    7: "../levels/Map7",
    8: "../levels/Map8",
    9: "../levels/Frostreach/ice_wall_gate",
    10: "../levels/Frostreach/expanse",
}

# A realistic dummy display size so YSortCameraGroup's viewport/grass subsurface
# are sane. The simulation is camera-independent (enemy AI runs over every
# enemy via the enemy_update sweep, not the view cull), so this affects only the
# never-presented draw half.
_DEFAULT_SIZE = (1280, 720)


def ensure_headless_display(size=_DEFAULT_SIZE):
    """Stand up the minimal pygame env Level4 construction needs headless:
    an initialized display *surface* (asset convert_alpha / the camera group's
    pygame.display.get_surface() need one; under SDL_VIDEODRIVER=dummy it's an
    offscreen surface, no window) and an initialized mixer (CombatUnit loads
    Sounds in __init__; silent no-ops under SDL_AUDIODRIVER=dummy).

    Idempotent: only initializes what's missing, so both the real server (which
    never calls pygame.init()) and the test suite (which does) work."""
    if not pygame.display.get_init():
        pygame.display.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode(size)
    if not pygame.mixer.get_init():
        try:
            pygame.mixer.init()
        except pygame.error:
            pass  # no audio device even under dummy -- Sound() would still fail,
            # but that's an environment problem, not something to paper over.


def build_headless_level(character_dir=None, level_number=6, size=_DEFAULT_SIZE,
                         is_server=True):
    """Construct and return the REAL Level4 at `level_number`, headless.

    Mirrors Main2._start_multiplayer_session / start_level but with a no-op
    StubBackend and no menus: pick a character's base stats, load the level. The
    returned level has a real player, spawner, layout_manager, quad trees, and
    combat context -- ready to tick.

    `is_server` (default True) drives Level4.run()'s render guards: True skips
    every draw-only call (the server path); False runs the full client loop
    headless (used by tests to compare the two paths' simulation).
    """
    ensure_headless_display(size)

    if character_dir is None or character_dir not in unlocked_player_directory:
        character_dir = unlocked_player_directory[0]
    character_index = unlocked_player_directory.index(character_dir)
    base_stats = unlocked_player_base_stats[character_index].copy()

    layouts_dir = _LEVEL_LAYOUTS.get(level_number, _LEVEL_LAYOUTS[6])

    level = Level4(
        InputManager(),
        character_dir,
        layouts_dir,
        base_stats,
        level_number=level_number,
        game_settings=GameSettings(),
        backend=StubBackend(*size),
        is_server=is_server,
    )
    return level
