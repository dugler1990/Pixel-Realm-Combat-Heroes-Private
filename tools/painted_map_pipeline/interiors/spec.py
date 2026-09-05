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
    tile: int = TILE
    schema_version: int = SCHEMA_VERSION

    # ------------------------------------------------------------------ derived

    @property
    def tiles(self) -> tuple:
        return (round(self.size[0] / self.tile, 1), round(self.size[1] / self.tile, 1))

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
        for key in ("origin", "size", "door_origin", "door_inward"):
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
    if art.door_point is not None:
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
