"""Walk the doorway in the real engine and save the frames.

The gate that has never existed. Every other check here measures a mask; this one shows what
the player will actually see crossing the threshold -- the roof lifting off, the arch split
at the feet, the interior underneath -- which is the thing being built and the only thing
that can say whether a plan is any good to walk through.

It runs the shipping code, not a reimplementation of it: a real Level4 on the scratch map,
its own YSortCameraGroup deciding the draw order, `CPUBackend` blitting to the display
surface, and `Level4.run(dt)` stepping it. A second copy of the compositing would be a
second thing to keep in step, and the whole point of the plan pass is to stop having two of
those.

Two rails it stands on, both already here: `Server/headless_level.py` builds a real Level4
under dummy SDL, and `Code/rts_validation_driver.py` already teleports the player and steps
scenarios.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
# Frames per waypoint. The view latch is hysteretic (a tile of margin on the way out) and
# the walk cycle phases on distance travelled, so a single tick after a teleport can catch
# the building mid-transition.
SETTLE_TICKS = 4
DT = 1.0 / 30.0


@dataclass(frozen=True)
class Waypoint:
    name: str
    tiles_inward: float
    caption: str


# Sampled along the door's inward normal, so they mean the same thing for any building
# whatever direction its entrance faces. Dense round the door line, because that is where
# the player was being hidden: walking up to the door, standing in it, passing the lintel.
WALK = (
    Waypoint("1_outside", -2.5, "outside: roof intact"),
    Waypoint("2_approach", -1.0, "walking up to the door"),
    Waypoint("3_close", -0.3, "just in front of the door"),
    Waypoint("4_threshold", 0.0, "on the door line"),
    Waypoint("5_doorway", 0.2, "in the doorway"),
    Waypoint("6_lintel", 0.5, "under the lintel"),
    Waypoint("7_through", 1.0, "through the door"),
    Waypoint("8_inside", 2.0, "inside: roof lifted, interior under"),
    Waypoint("9_deep", 5.0, "deep inside"),
)


def _boot(size=(1280, 720)):
    """Bring the engine up headless. Imports are here, not at module scope: Settings chdirs
    to Code/ on import, so anything that happens before this must already have resolved its
    paths."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    for path in (REPO / "Code", REPO / "Server"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))

    import pygame

    pygame.init()
    pygame.display.quit()
    pygame.display.init()
    pygame.display.set_mode(size)
    return pygame


def _level(pygame, layouts_dir: Path):
    """A real Level4 on `layouts_dir`, drawing to the display surface.

    `build_headless_level` hardcodes a level number to a layout, and hands it a StubBackend
    that draws nothing -- right for a server, useless for a picture. So Level4 is
    constructed directly with the same arguments and a CPUBackend instead.
    """
    from game_settings import GameSettings
    from headless_level import ensure_headless_display
    from inputManager import InputManager
    from Level4_tmxdev import Level4
    from PlayerSelection import unlocked_player_base_stats, unlocked_player_directory
    from render_backend import CPUBackend

    # The same bootstrap the server uses: a display surface for convert_alpha and the camera
    # group, and a mixer because CombatUnit loads sounds in __init__.
    ensure_headless_display()
    surface = pygame.display.get_surface()
    character = unlocked_player_directory[0]
    stats = unlocked_player_base_stats[0].copy()
    relative = os.path.relpath(layouts_dir, REPO / "Code")
    return Level4(
        InputManager(),
        character,
        relative,
        stats,
        level_number=6,
        game_settings=GameSettings(),
        backend=CPUBackend(surface),
        is_server=False,
    )


def _teleport(level, position):
    """Move the player, hitbox and rect together.

    Setting only rect leaves the hitbox behind and the camera follows the hitbox, so the
    frame would be of the wrong place. rts_validation_driver does the same three writes.
    """
    player = level.player
    player.hitbox.center = (int(position[0]), int(position[1]))
    player.rect.center = player.hitbox.center
    if hasattr(player, "plant_sprite_on_hitbox"):
        player.plant_sprite_on_hitbox()
    for attribute in ("pos", "world_pos"):
        if hasattr(player, attribute):
            try:
                setattr(player, attribute, pygame.math.Vector2(player.hitbox.center))
            except Exception:
                pass


def waypoints(spec, scale: float = 1.0):
    """The walk, in the game's world px, along the entrance's inward normal.

    `scale` is the map's `world_scale`: the game draws a map with tilewidth 120 at 1.25x, so
    a point in map px is at 1.25x that in the world. Without it the walk on sunspine landed
    inside the wrong pyramid.
    """
    if not spec.door_origin or not spec.door_inward:
        raise ValueError(f"{spec.building} has no door plane; nothing to walk through")
    ox = spec.origin[0] + spec.door_origin[0]
    oy = spec.origin[1] + spec.door_origin[1]
    for point in WALK:
        distance = point.tiles_inward * spec.tile
        yield point, ((ox + spec.door_inward[0] * distance) * scale,
                      (oy + spec.door_inward[1] * distance) * scale)


def filmstrip(spec, layouts_dir: Path, out_dir: Path, size=(1280, 720)) -> list:
    """Save one frame per waypoint. Returns the paths written."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    layouts_dir = Path(layouts_dir).resolve()
    # Before the engine boots: importing Settings changes folder to Code/, after which the
    # map's relative path no longer opens and `world_scale` falls back to 1.
    scale = spec.world_scale

    global pygame
    pygame = _boot(size)
    cwd = os.getcwd()
    try:
        level = _level(pygame, layouts_dir)
        written = []
        for point, position in waypoints(spec, scale):
            _teleport(level, position)
            for _ in range(SETTLE_TICKS):
                level.run(DT)
            path = out_dir / f"{spec.building}_{point.name}.png"
            pygame.image.save(pygame.display.get_surface(), str(path))
            written.append((path, point.caption))
            print(f"  {point.name}: {point.caption} -> {path.name}")
        return written
    finally:
        os.chdir(cwd)


def contact_strip(frames, out_path: Path, width: int = 420) -> Path:
    """The frames side by side with their captions, so the transition reads as a sequence."""
    from PIL import Image, ImageDraw

    thumbs = []
    for path, caption in frames:
        thumb = Image.open(path).convert("RGB")
        thumb.thumbnail((width, width))
        thumbs.append((thumb, caption))
    height = max(t.height for t, _ in thumbs)
    strip = Image.new(
        "RGB",
        (sum(t.width for t, _ in thumbs) + 8 * (len(thumbs) - 1), height + 26),
        (20, 20, 20),
    )
    draw = ImageDraw.Draw(strip)
    x = 0
    for thumb, caption in thumbs:
        strip.paste(thumb, (x, 26))
        draw.text((x + 5, 7), caption[:56], fill=(235, 210, 120))
        x += thumb.width + 8
    strip.save(out_path)
    return out_path
