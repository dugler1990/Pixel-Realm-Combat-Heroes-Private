"""How big the player actually is, measured from the sprites rather than assumed.

Everything about a floor plan -- how wide a corridor has to be, how much of a building a
doorway should take -- depends on this number, and it was previously a constant nobody had
checked. The constant said 150 px, one tile.

It is not a tile. `Player.scale_animation` would scale every frame to (TILESIZE, TILESIZE),
but its body is guarded by `if hasattr(self, "TILESIZE")` and the line that would set it --
`Player.py:42` -- is commented out (`#self.TILESIZE = TILESIZE * 0.4# hardcoded bs fix it.`).
Nothing else sets it, on `Player` or `Entity`. So the scaling never runs and **the player is
drawn at the sprite's own native size**: 61 px for the wizard, 53 for the barbarian, 27 for
barb_small.

Which makes this a measurement of the ART AS SHIPPED, not of what the code intends. The old
150 px constant was demanding two and a half times the clearance any character needs.

`CHARACTER` is who the plans are sized for. The roster holds three, and their sprites differ
by more than 2x (61 px wizard, 53 px barb, 27 px barb_small) -- which is a fact about the art
being unfinished rather than a design decision, so taking the widest would size every corridor
in the game to whichever sprite happens to be biggest today. Sizing to the barbarian is a
choice, and it is written here as one.

What is measured is the sprite's opaque extent, because collision is `rect` + `mask` through
the quadtree (`Entity.py`) -- the mask is the player. The hitbox (`rect.inflate(-6, -26)`,
about 144 x 124) only carries position; it is not what the world collides with.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
TILE = 150

# The roster the game actually offers, not every folder under Graphics/. That directory also
# holds dev leftovers -- `barb_clump_preview`, `barb_range_wipe_test`, `Orange_Wizard (copy)`
# -- and the widest of those is 129 px, wider than any character a player can choose. Sizing
# corridors to a test asset would make every plan harder to satisfy for no reason.
ROSTER = "Graphics/PlayerSelectionDict.json"
WALK_FRAMES = "down/*.png"

# The character the interiors are built around. Change this and every corridor, doorway and
# passability check follows, which is the point of it being one name in one place.
CHARACTER = "barb"

# Fallback when the roster cannot be read. Deliberately narrow -- it takes the folders that
# look like a character rather than everything, and says so when it is used.
SPRITE_GLOB = "Graphics/*/down/*.png"

# Alpha at or below this is background. Sprites are cut cleanly, so this only discards the
# odd anti-aliased edge pixel rather than trimming the character.
OPAQUE = 8


@dataclass(frozen=True)
class PlayerSize:
    """The widest character, in world pixels at TILE scale."""

    width: int
    height: int
    character: str
    sprite: str
    tile: int = TILE
    measured: bool = True          # False when nothing was found and TILE was assumed

    @property
    def half_width_tiles(self) -> float:
        """What `checks.player_half_width` wants: half the character, in tiles."""
        return (self.width / 2.0) / float(self.tile)

    @property
    def tiles(self) -> float:
        return self.width / float(self.tile)

    def at_scale(self, scale: float) -> "PlayerSize":
        """This player in the pixel space of art the engine draws `scale` times bigger."""
        if not scale or abs(scale - 1.0) < 1e-9:
            return self
        return PlayerSize(
            width=max(1, int(round(self.width / scale))),
            height=max(1, int(round(self.height / scale))),
            character=self.character, sprite=self.sprite,
            tile=self.tile, measured=self.measured,
        )

    def describe(self) -> str:
        if not self.measured:
            return (f"player {self.width} x {self.height} px (ASSUMED -- no sprites found, "
                    f"using the tile size)")
        return (f"player {self.width} x {self.height} px "
                f"({self.tiles:.2f} tiles wide, sized for: {self.character})")


def _opaque_extent(path: Path) -> tuple:
    """The sprite's opaque bounding box, in world pixels.

    No scaling by the frame or the tile: the frames are blitted as they are, because
    `scale_animation` is dead behind an unset attribute. The opaque box IS the player, and it
    is what collision sees -- collision runs `rect` + `mask` through the quadtree
    (`Entity.py`), so the mask is the authority.
    """
    with Image.open(path) as image:
        alpha = np.asarray(image.convert("RGBA"))[..., 3]
    rows, columns = np.where(alpha > OPAQUE)
    if not len(columns):
        return None
    return (int(columns.max() - columns.min() + 1), int(rows.max() - rows.min() + 1))


def roster(repo: Path) -> list:
    """Every character a player can actually choose, from the game's own selection file."""
    try:
        listed = json.loads((repo / ROSTER).read_text(encoding="utf-8"))["Players"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    names = [str(entry.get("name", "")).strip() for entry in listed]
    return [name for name in names if name]


def sprites(repo: Path, character: str = CHARACTER) -> list:
    """The chosen character's walk frames, or anything that looks like a character."""
    frames = sorted((repo / "Graphics" / character).glob(WALK_FRAMES))
    if frames:
        return frames
    listed = roster(repo)
    print(f"  no walk frames for {character!r} under Graphics/; the roster offers {listed}. "
          f"Measuring whatever sprites exist instead.")
    return sorted(repo.glob(SPRITE_GLOB))


def measure(repo: Path = None, character: str = CHARACTER) -> PlayerSize:
    """The character the interiors are sized for, at its widest frame.

    Widest FRAME, not widest character: a walk cycle swings the arms, and a corridor that fits
    the idle pose but not mid-stride is a corridor you get stuck in.
    """
    repo = Path(repo or REPO)
    widest = None
    for sprite in sprites(repo, character):
        extent = _opaque_extent(sprite)
        if extent is None:
            continue
        if widest is None or extent[0] > widest[0][0]:
            widest = (extent, sprite)

    if widest is None:
        print(f"  no character sprites under {repo / SPRITE_GLOB}; assuming the player is a "
              f"whole tile ({TILE} px). Corridor checks will be far stricter than they need "
              f"to be -- the real character is around 53 px.")
        return PlayerSize(width=TILE, height=TILE, character="unknown", sprite="",
                          measured=False)

    (width, height), sprite = widest
    return PlayerSize(width=width, height=height,
                      character=sprite.parent.parent.name,
                      sprite=str(sprite.relative_to(repo).as_posix()))


def player_size(cache: Path = None, refresh: bool = False, scale: float = 1.0) -> PlayerSize:
    """The measurement, read from cache when it is there, in the caller's pixel space.

    Cached because it opens every character sprite, and the answer only changes when the art
    does -- but kept in a file you can delete rather than a constant you have to find.

    `scale` is the level's `spec.world_scale`: the sprite is measured in game px, but the
    plan canvas is painted px, and the engine draws painted art `scale` times bigger. A
    53 px sprite standing on art drawn at 1.25x is 42 px of that art. The cache holds the
    game-px measurement; the divide happens here, on the way out, so the cache is one file
    regardless of how many levels draw at how many scales.
    """
    cache = Path(cache or REPO / "generated" / "building_interiors" / "player_size.json")
    found = None
    if cache.exists() and not refresh:
        try:
            found = PlayerSize(**json.loads(cache.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            found = None                            # stale or hand-edited: measure again

    if found is None:
        found = measure()
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(asdict(found), indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass                                    # a cache that cannot be written is fine
    return found.at_scale(scale)
