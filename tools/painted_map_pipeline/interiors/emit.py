"""Traced floor plan -> chamber polygon and collision quads, written to a scratch TMX.

Why a new emitter rather than `building_walls.wall_segments`: that one tiles the inside face
of a single convex ring and skips one gap, and `inset_polygon` is convex-only by
construction. A traced plan is neither -- it has a corridor, partitions between rooms, and
sometimes a solid island standing in a room. This walks each traced boundary's own edges
instead, which handles all three and needs no convexity.

What it keeps from that module is the reason the quads are short. An entity's push-out
direction comes from the obstacle's bounding-rect CENTRE, not the contact point, so a long
segment pushes anyone touching its end sideways instead of away. Short segments keep the
AABB centre near the contact point.

Why a scratch TMX: writing is regex string surgery on the shipped map, idempotent only by
name prefix, so a half-failed write leaves it partly stripped. The preview loads whatever
path it is handed, so it stays honest against a copy.
"""

from __future__ import annotations

import math
import os
import re
import shutil
from pathlib import Path

import numpy as np

from ..world_levels.geometry import mask_to_polygon
from .trace import to_world

# Matches building_walls: short enough that the push-out direction stays locally correct.
SEGMENT_LENGTH = 220.0
WALL_THICKNESS = 160.0
# A traced boundary shorter than this is trace noise, not a wall.
MIN_BOUNDARY_PERIMETER = 240.0


def chamber_from_plan(plan) -> tuple:
    """The chamber: traced floor plus its wall band, as one polygon.

    Pinned here because three consumers read it and they must not drift -- the art mask, the
    view latch that decides when the roof lifts off, and `build_masks`' assertion that the
    chamber lies inside the silhouette. Deriving it from the trace rather than from an inset
    of the silhouette is the whole point: the authored inset called 74% of a solid pyramid a
    room, which no painting of it could ever agree with.
    """
    occupied = (plan.classes["floor"] | plan.classes["wall"]) & plan.silhouette
    if not occupied.any():
        raise ValueError("plan has no floor: nothing to derive a chamber from")
    return to_world(mask_to_polygon(occupied, epsilon_frac=0.004), plan.spec.origin)


def wall_quads(plan, thickness=WALL_THICKNESS, seg_len=SEGMENT_LENGTH) -> list:
    """Short quads along every traced floor boundary, outward into the wall band.

    Outers get their quads laid outward and holes inward, so in both cases the stone sits on
    the solid side of the boundary and the floor stays clear.
    """
    quads = []
    for boundary in _boundaries(plan):
        polygon = boundary.polygon
        centre = _centroid(polygon)
        for index in range(len(polygon)):
            p, q = polygon[index], polygon[(index + 1) % len(polygon)]
            length = math.hypot(q[0] - p[0], q[1] - p[1])
            if length < 1.0:
                continue
            ux, uy = (q[0] - p[0]) / length, (q[1] - p[1]) / length
            # Outward from the floor: away from an outer boundary's centre, towards a hole's.
            nx, ny = -uy, ux
            towards = (centre[0] - (p[0] + q[0]) / 2.0) * nx + (centre[1] - (p[1] + q[1]) / 2.0) * ny
            if (towards > 0) != boundary.is_hole:
                nx, ny = -nx, -ny
            steps = max(1, int(math.ceil(length / seg_len)))
            step = length / steps
            for s in range(steps):
                t0, t1 = s * step, (s + 1) * step
                a = (p[0] + ux * t0, p[1] + uy * t0)
                b = (p[0] + ux * t1, p[1] + uy * t1)
                quads.append([
                    a, b,
                    (b[0] + nx * thickness, b[1] + ny * thickness),
                    (a[0] + nx * thickness, a[1] + ny * thickness),
                ])
    return quads


def rooms(plan, radius=None) -> list:
    """Eroded floor components as world polygons: one per room.

    Rooms are the natural unit for spawning, and this is the same erosion `room_count`
    measures, so what gets a spawn area is exactly what was counted.
    """
    from . import checks as layout_checks
    from .trace import component_report

    radius = radius or layout_checks.CORRIDOR_HALF_TILES * plan.spec.tile
    eroded = layout_checks.erode(plan.floor, radius)
    minimum = int(layout_checks.MIN_ROOM_TILES_SQ * plan.spec.tile * plan.spec.tile)
    out = []
    import cv2

    number, labels = cv2.connectedComponents(
        np.ascontiguousarray(eroded.astype(np.uint8)), connectivity=8)
    for label in range(1, number):
        component = labels == label
        if int(component.sum()) < minimum:
            continue
        try:
            out.append(to_world(mask_to_polygon(component, epsilon_frac=0.02), plan.spec.origin))
        except ValueError:
            continue
    return out


def _boundaries(plan):
    from .trace import trace_boundaries

    return [b for b in trace_boundaries(plan.floor)
            if _perimeter(b.polygon) >= MIN_BOUNDARY_PERIMETER]


def _perimeter(polygon) -> float:
    return sum(
        math.hypot(polygon[(i + 1) % len(polygon)][0] - polygon[i][0],
                   polygon[(i + 1) % len(polygon)][1] - polygon[i][1])
        for i in range(len(polygon)))


def _centroid(points):
    n = float(len(points))
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)


# ---------------------------------------------------------------- TMX writing

_OBJECT_RE = re.compile(r"[ \t]*<object\b[^>]*\bname=\"(?P<name>[^\"]*)\"[^>]*?"
                        r"(?:/>|>.*?</object>)\s*\n", re.S)


def _strip_prefixed(xml, prefix):
    return _OBJECT_RE.sub(lambda m: "" if m.group("name").startswith(prefix) else m.group(0), xml)


def _next_object_id(xml) -> int:
    ids = [int(m) for m in re.findall(r"<object\b[^>]*\bid=\"(\d+)\"", xml)]
    return (max(ids) + 1) if ids else 1


def _object_xml(obj_id, name, points, props=None) -> str:
    ox = int(round(min(p[0] for p in points)))
    oy = int(round(min(p[1] for p in points)))
    rel = " ".join("%d,%d" % (int(round(x)) - ox, int(round(y)) - oy) for x, y in points)
    lines = ['  <object id="%d" name="%s" x="%d" y="%d">' % (obj_id, name, ox, oy),
             '   <polygon points="%s"/>' % rel]
    if props:
        lines.append("   <properties>")
        for key, value in props.items():
            lines.append('    <property name="%s" value="%s"/>' % (key, value))
        lines.append("   </properties>")
    lines.append("  </object>")
    return "\n".join(lines) + "\n"


def _insert_into_layer(xml, layer, block) -> str:
    match = re.search(r'[ \t]*<objectgroup\b[^>]*\bname="%s"[^>]*>\n' % re.escape(layer), xml)
    if not match:
        raise ValueError(f"no {layer!r} object layer in the map")
    return xml[:match.end()] + block + xml[match.end():]


def scratch_level(spec) -> Path:
    """A shadow of the level folder whose map.tmx is the one plans are written into.

    A whole folder rather than a stray file because the engine takes a layout DIRECTORY and
    loads `map.tmx` from it, and because tilesets and building art resolve relative to the
    map. Everything but the map is symlinked, so shadowing a level with a 242 MB background
    costs nothing.

    The shipped map is never written until accept. That matters more than churn: writing is
    regex surgery, idempotent only by name prefix, so a half-failed write leaves the real
    map partly stripped.
    """
    source_dir = Path(spec.map_path).resolve().parent
    scratch_dir = source_dir.parent / f"{source_dir.name}.plan"
    scratch_dir.mkdir(parents=True, exist_ok=True)

    for entry in source_dir.iterdir():
        target = scratch_dir / entry.name
        if entry.name == "map.tmx":
            shutil.copyfile(entry, target)
            continue
        if entry.name == "initial_layout_name.txt":
            continue
        if target.is_symlink() or target.exists():
            continue
        target.symlink_to(entry.resolve())

    # The engine reads this as a path relative to Code/, so the shadow has to name itself.
    code_dir = Path(__file__).resolve().parents[3] / "Code"
    (scratch_dir / "initial_layout_name.txt").write_text(
        os.path.relpath(scratch_dir, code_dir) + "\n", encoding="utf-8")
    return scratch_dir


def write_plan(plan, map_path: Path, *, obstacle_layer="ObstaclePolygons",
               building_layer="Buildings", spawn_layer=None) -> dict:
    """Replace this building's generated geometry in `map_path` with the plan's.

    Idempotent by name prefix, like building_walls: every object this writes is named
    `<building>_wall_NN`, `<building>_chamber` or `<building>_room_NN`, and re-running
    replaces exactly those and leaves hand-authored objects alone.
    """
    building = plan.spec.building
    xml = Path(map_path).read_text(encoding="utf-8")
    for prefix in (f"{building}_wall", f"{building}_chamber", f"{building}_room"):
        xml = _strip_prefixed(xml, prefix)

    obj_id = _next_object_id(xml)
    quads = wall_quads(plan)
    walls_xml = ""
    for index, quad in enumerate(quads):
        walls_xml += _object_xml(obj_id, "%s_wall_%02d" % (building, index), quad)
        obj_id += 1

    chamber = chamber_from_plan(plan)
    chamber_xml = _object_xml(obj_id, f"{building}_chamber", chamber,
                              {"chamber_of": building})
    obj_id += 1

    room_polygons = rooms(plan)
    rooms_xml = ""
    for index, polygon in enumerate(room_polygons):
        rooms_xml += _object_xml(obj_id, "%s_room_%02d" % (building, index), polygon,
                                 {"room_of": building})
        obj_id += 1

    xml = _insert_into_layer(xml, obstacle_layer, walls_xml)
    xml = _insert_into_layer(xml, building_layer, chamber_xml)
    if rooms_xml:
        xml = _insert_into_layer(xml, spawn_layer or building_layer, rooms_xml)
    xml = re.sub(r'nextobjectid="\d+"', 'nextobjectid="%d"' % obj_id, xml, count=1)
    Path(map_path).write_text(xml, encoding="utf-8")

    return {
        "map": str(map_path),
        "walls": len(quads),
        "chamber": [(int(x), int(y)) for x, y in chamber],
        "rooms": len(room_polygons),
    }
