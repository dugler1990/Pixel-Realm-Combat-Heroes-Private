#!/usr/bin/env python3
"""Generate a building's wall-ring collision (and matching chamber) into a TMX map.

Why a generator rather than hand-placing quads in Tiled: the ring is forty-odd
segments, and it has to be regenerated whenever the silhouette, the wall thickness
or the door position changes. Hand-maintaining that is error-prone, and the chamber
polygon has to stay exactly the silhouette inset by the wall thickness or the reveal
region drifts away from the walls.

Why many small quads rather than one polygon: an entity's push-out direction comes
from the obstacle's bounding-rect CENTRE (collision_core.rect_rebound_dir), not the
contact point -- mask-derived normals are opt-in per unit profile and off for the
player. A single hollow ring would therefore push anyone standing inside it outward
THROUGH the wall. Short segments keep the AABB centre near the contact point, so the
push direction stays locally correct.

Re-running is idempotent: objects whose name starts with the prefix are replaced.

    python3 tools/building_walls.py --dry-run       # print what would change
    python3 tools/building_walls.py                 # write it
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys

# The polygon maths is shared with the game's Building and with the interior generator, so
# it lives in Code/ and is reached the way the tests reach it. The dependency only points
# this way: Code/ never imports from tools/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Code"))

from building_geometry import (  # noqa: E402
    centroid,
    inset_polygon,
    inward_normal,
    nearest_edge,
)

# Great pyramid, sunspine_7x6_play. World px; this map is 1:1 with TMX units
# (tilewidth 150 == TILESIZE 150), so no scaling is needed here.
DEFAULT_MAP = "levels/Frostreach/sunspine_7x6_play/map.tmx"
DEFAULT_CORNERS = [(7620, 2690), (9450, 4410), (7700, 5830), (5850, 4170)]
DEFAULT_DOOR = (8430, 4970)


def wall_segments(corners, seg_len, thickness, door, door_gap):
    """Quads tiling the inside face of each edge, skipping the doorway."""
    centre = centroid(corners)

    # The door sits on whichever edge it is nearest; only that edge gets a gap.
    door_edge, projection = nearest_edge(corners, door)
    door_t, door_dist = projection.along, projection.perpendicular

    quads = []
    for i in range(len(corners)):
        p, q = corners[i], corners[(i + 1) % len(corners)]
        ex, ey = q[0] - p[0], q[1] - p[1]
        length = math.hypot(ex, ey)
        ux, uy = ex / length, ey / length
        nx, ny = inward_normal(p, q, centre)

        steps = max(1, int(math.ceil(length / seg_len)))
        step = length / steps
        for s in range(steps):
            t0, t1 = s * step, (s + 1) * step
            if i == door_edge and t1 > door_t - door_gap / 2.0 and t0 < door_t + door_gap / 2.0:
                continue  # doorway
            a = (p[0] + ux * t0, p[1] + uy * t0)
            b = (p[0] + ux * t1, p[1] + uy * t1)
            c = (b[0] + nx * thickness, b[1] + ny * thickness)
            d = (a[0] + nx * thickness, a[1] + ny * thickness)
            quads.append([a, b, c, d])
    return quads, door_edge, door_t, door_dist


def _object_xml(obj_id, name, points, props=None):
    ox = int(round(min(p[0] for p in points)))
    oy = int(round(min(p[1] for p in points)))
    rel = " ".join("%d,%d" % (int(round(x)) - ox, int(round(y)) - oy) for x, y in points)
    lines = ['  <object id="%d" name="%s" x="%d" y="%d">' % (obj_id, name, ox, oy),
             '   <polygon points="%s"/>' % rel]
    if props:
        lines.append("   <properties>")
        for k, v in props.items():
            lines.append('    <property name="%s" value="%s"/>' % (k, v))
        lines.append("   </properties>")
    lines.append("  </object>")
    return "\n".join(lines) + "\n"


_OBJECT_RE = re.compile(r"[ \t]*<object\b[^>]*\bname=\"(?P<name>[^\"]*)\"[^>]*?"
                        r"(?:/>|>.*?</object>)\s*\n", re.S)


def _strip_prefixed(xml, prefix):
    """Drop objects whose name starts with `prefix`, leaving hand-authored ones."""
    return _OBJECT_RE.sub(lambda m: "" if m.group("name").startswith(prefix) else m.group(0), xml)


def _next_object_id(xml):
    ids = [int(m) for m in re.findall(r"<object\b[^>]*\bid=\"(\d+)\"", xml)]
    return (max(ids) + 1) if ids else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", default=DEFAULT_MAP)
    ap.add_argument("--prefix", default="great_pyramid_wall",
                    help="generated wall objects are named <prefix>_NN and replaced on re-run")
    ap.add_argument("--chamber-name", default="great_pyramid_chamber")
    ap.add_argument("--chamber-of", default="great_pyramid")
    ap.add_argument("--layer", default="ObstaclePolygons")
    ap.add_argument("--seg-len", type=float, default=220.0,
                    help="wall segment length; shorter = better push direction, more obstacles")
    ap.add_argument("--thickness", type=float, default=160.0)
    ap.add_argument("--door-gap", type=float, default=400.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    corners, door = DEFAULT_CORNERS, DEFAULT_DOOR
    quads, door_edge, door_t, door_dist = wall_segments(
        corners, args.seg_len, args.thickness, door, args.door_gap)
    chamber = inset_polygon(corners, args.thickness)

    print("walls    : %d segments (%.0fpx each, %.0fpx thick)"
          % (len(quads), args.seg_len, args.thickness))
    print("door gap : edge %d at %.0f along it, %.0fpx wide (door is %.0fpx off the edge)"
          % (door_edge, door_t, args.door_gap, door_dist))
    print("chamber  : %s" % [(int(x), int(y)) for x, y in chamber])

    with open(args.map, encoding="utf-8") as fh:
        xml = fh.read()

    xml = _strip_prefixed(xml, args.prefix)
    xml = _strip_prefixed(xml, args.chamber_name)

    obj_id = _next_object_id(xml)
    walls_xml = ""
    for i, quad in enumerate(quads):
        walls_xml += _object_xml(obj_id, "%s_%02d" % (args.prefix, i), quad)
        obj_id += 1
    chamber_xml = _object_xml(obj_id, args.chamber_name, chamber,
                              {"chamber_of": args.chamber_of})
    obj_id += 1

    # Walls go on their own registered obstacle layer; the chamber belongs with the
    # building it describes.
    layer_open = re.search(r'[ \t]*<objectgroup\b[^>]*\bname="%s"[^>]*>\n' % re.escape(args.layer),
                           xml)
    if layer_open:
        xml = xml[:layer_open.end()] + walls_xml + xml[layer_open.end():]
    else:
        block = ' <objectgroup id="%d" name="%s">\n%s </objectgroup>\n' % (
            _next_layer_id(xml), args.layer, walls_xml)
        xml = xml.replace("</map>", block + "</map>")
        xml = _bump_layer_id(xml)

    buildings = re.search(r'[ \t]*<objectgroup\b[^>]*\bname="Buildings"[^>]*>\n', xml)
    if not buildings:
        sys.exit("no Buildings layer in %s" % args.map)
    xml = xml[:buildings.end()] + chamber_xml + xml[buildings.end():]

    xml = re.sub(r'nextobjectid="\d+"', 'nextobjectid="%d"' % obj_id, xml, count=1)

    if args.dry_run:
        print("\n-- dry run, not written --")
        return 0
    with open(args.map, "w", encoding="utf-8") as fh:
        fh.write(xml)
    print("wrote %s" % args.map)
    return 0


def _next_layer_id(xml):
    ids = [int(m) for m in re.findall(r"<(?:layer|objectgroup|imagelayer)\b[^>]*\bid=\"(\d+)\"", xml)]
    return (max(ids) + 1) if ids else 1


def _bump_layer_id(xml):
    return re.sub(r'nextlayerid="\d+"', 'nextlayerid="%d"' % (_next_layer_id(xml) + 1), xml, count=1)


if __name__ == "__main__":
    raise SystemExit(main())
