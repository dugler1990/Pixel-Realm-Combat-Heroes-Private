"""What the interview produces, and the only thing the rest of the pipeline reads.

Two answers are asked for per building -- what the object is, and how its entrance looks --
because those are the only two that cannot be derived. Everything else on this record is
computed from the map and the art and shown back rather than asked: the canvas, the scale in
characters, the threshold's width and where it sits on the silhouette.

The spec is persisted so a rerun never re-asks, and so a plan can be traced, emitted and
rendered in separate sessions against identical geometry.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from ..building_interiors import BuildingArt, load_building
from .runtime import building_geometry
from .trace import to_world

SCHEMA_VERSION = 1
TILE = 150

# A partition between two rooms, as a fraction of the building's own outer shell. Derived
# rather than typed, because there is one measured wall -- `ask_model` reading the building's
# art -- and everything about the interior's shape should follow from it.
#
# Thinner than the shell, which is the right way round and was not what the code did: the
# constant this replaces made partitions 160 px against a 70 px shell, so the wall band
# dilated across the whole chamber and the plan overlay read as a solid sheet.
INNER_WALL_FRACTION = 0.6
MIN_INNER_WALL = 24

_WORLD_SCALE_CACHE: dict = {}


def world_scale_of(map_path) -> float:
    """`TILESIZE / tilewidth` for a TMX, the factor the engine draws it at. 1.0 if unreadable.

    Read from the <map> tag directly rather than through pytmx, which would decode every
    image the map references (the painted ground is ~1 GB) just to get one attribute.
    """
    import re

    key = str(map_path)
    cached = _WORLD_SCALE_CACHE.get(key)
    if cached is not None:
        return cached
    scale = 1.0
    try:
        head = Path(map_path).read_text(encoding="utf-8")[:4096]
        found = re.search(r'<map\b[^>]*\btilewidth="(\d+(?:\.\d+)?)"', head)
        if found and float(found.group(1)) > 0:
            scale = TILE / float(found.group(1))
    except OSError:
        pass
    _WORLD_SCALE_CACHE[key] = scale
    return scale


@dataclass
class InteriorSpec:
    building: str
    map_path: str
    origin: tuple            # world px of the canvas top-left
    size: tuple              # canvas px
    silhouette: tuple        # canvas-local polygon
    chamber: tuple           # canvas-local polygon, as authored (superseded by the trace)
    doors: tuple             # canvas-local polygons held out of the editable region
    roof_image: str
    interior_image: str
    door_origin: tuple = None    # canvas-local point on the silhouette edge
    door_inward: tuple = None    # unit normal pointing into the building
    arch_quad: tuple = ()        # canvas-local threshold quad
    object_prompt: str = ""      # "pyramid" -- what the object is
    entrance_prompt: str = ""    # "dark doorway with stone lintel"
    intent: str = ""             # what is inside, free text, steers the plan pass
    rooms: int = None            # expected room count, checkable after the trace
    wall: int = None             # px of wall the chamber was inset by, when it was derived
    inner_wall: int = None       # partition between rooms; None means derive it from `wall`
    door_gap: float = None       # the opening along the wall; None means the game's default
    corridor_players: tuple = None   # how many players wide a corridor should be, when set
    room_players: tuple = None       # how many players across a room should be, when set
    scale_character: str = ""        # who stands in the room while it is decorated; "" = barb
    scale_at: tuple = None           # canvas px of his feet; None = the floor farthest from a wall
    tile: int = TILE
    schema_version: int = SCHEMA_VERSION

    # ------------------------------------------------------------------ derived

    @property
    def tiles(self) -> tuple:
        return (round(self.size[0] / self.tile, 1), round(self.size[1] / self.tile, 1))

    @property
    def world_scale(self) -> float:
        """How much bigger the game draws this level's painted art than it is on disk.

        The engine scales everything from a TMX by `TILESIZE / tmx.tilewidth` at load, so a
        map authored at tilewidth 120 draws at 1.25x. This canvas is in painted px, and the
        player is measured in game px, so anything comparing the two -- the figure pasted for
        scale, the corridor checks, "a person is N px" in the prompt -- divides by this.
        """
        return world_scale_of(self.map_path)

    @property
    def partition(self) -> int:
        """Thickness of a wall between rooms, in px.

        The one number the control image's wall band and the collision quads both read, so
        what you are shown and what you walk into cannot drift apart.
        """
        if self.inner_wall:
            return int(self.inner_wall)
        if not self.wall:
            return MIN_INNER_WALL
        return int(max(MIN_INNER_WALL, INNER_WALL_FRACTION * self.wall))

    @property
    def door_width(self) -> float:
        """Width of the authored threshold along the wall, in px."""
        if not self.arch_quad:
            return 0.0
        (ax, ay), (bx, by) = self.arch_quad[0], self.arch_quad[1]
        return float(np.hypot(bx - ax, by - ay))

    def world(self, polygon) -> tuple:
        return to_world(polygon, self.origin)

    # ------------------------------------------------------------------ io

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "InteriorSpec":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if raw.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"{path} was written by schema {raw.get('schema_version')}, this is "
                f"{SCHEMA_VERSION}; re-run the interview rather than guessing at the gap")
        for key in ("corridor_players", "room_players"):
            if raw.get(key) is not None:
                raw[key] = tuple(raw[key])
        for key in ("origin", "size", "door_origin", "door_inward", "scale_at"):
            if raw.get(key) is not None:
                raw[key] = tuple(raw[key])
        for key in ("silhouette", "chamber", "doors", "arch_quad"):
            raw[key] = tuple(tuple(point) for point in raw[key])
        return cls(**raw)


def _tuples(polygon):
    return tuple((float(x), float(y)) for x, y in polygon)


def from_building(art: BuildingArt, map_path: Path, **answers) -> InteriorSpec:
    """Build a spec from a TMX building plus the interview answers.

    The door plane comes from `door_plane_from_polygon`, the same call the game makes to
    decide where the roof splits in the doorway -- so the threshold the model is asked to
    paint into, the gap collision leaves, and the seam the player walks through are one
    piece of geometry rather than three that have to be kept in step.
    """
    door_origin = door_inward = None
    arch = ()
    door_gap = getattr(art, "door_gap", None)
    if art.door_point is not None:
        if door_gap:
            door_origin, door_inward, arch = building_geometry().door_plane_from_polygon(
                art.footprint, art.door_point, door_gap=door_gap)
        else:
            # Nothing measured the opening, so the game's DEFAULT_DOOR_GAP stands in. Said out
            # loud: it is a fixed 400 px whatever the building, which is 11% of a large
            # pyramid's frontage and 40% of a small one's.
            print(f"  {art.name}: no measured doorway; falling back to the game's default gap")
            door_origin, door_inward, arch = building_geometry().door_plane_from_polygon(
                art.footprint, art.door_point)
    return InteriorSpec(
        building=art.name,
        map_path=str(map_path),
        origin=tuple(art.origin),
        size=tuple(art.size),
        silhouette=_tuples(art.footprint),
        chamber=_tuples(art.chamber),
        doors=tuple(_tuples(door) for door in art.doors),
        roof_image=str(art.roof_path),
        interior_image=str(art.interior_path),
        door_origin=tuple(door_origin) if door_origin else None,
        door_inward=tuple(door_inward) if door_inward else None,
        arch_quad=_tuples(arch),
        door_gap=door_gap,
        **answers,
    )


def from_map(map_path: Path, building: str, **answers) -> InteriorSpec:
    return from_building(load_building(Path(map_path), building), Path(map_path), **answers)


def describe(spec: InteriorSpec) -> str:
    """The computed facts, shown rather than asked. Anything a person would otherwise be
    tempted to type into a prompt as a number belongs on this list instead."""
    lines = [
        f"{spec.building}: canvas {spec.size[0]} x {spec.size[1]} px at world {spec.origin}",
        f"  scale       {spec.tiles[0]} x {spec.tiles[1]} characters (tile {spec.tile} px)",
    ]
    if spec.door_origin:
        lines.append(
            f"  threshold   {spec.door_width:.0f} px "
            f"({spec.door_width / spec.tile:.1f} characters) at canvas "
            f"({spec.door_origin[0]:.0f}, {spec.door_origin[1]:.0f})")
        lines.append(
            f"  facing      inward normal "
            f"({spec.door_inward[0]:.2f}, {spec.door_inward[1]:.2f})")
    else:
        lines.append("  threshold   NOT AUTHORED -- no door_x/door_y on the building object")
    lines.append(f"  exterior    {spec.roof_image}")
    return "\n".join(lines)
