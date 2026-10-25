"""Polygon geometry shared by the game's buildings and the art pipeline that generates them.

`Building.py` and `tools/building_walls.py` grew byte-identical copies of `_centroid` and
`_inward_normal`, and two variants of `_project_onto_edge` that differ only in which of the
same four numbers they return. The interior generator needs the same functions a third time
— its entrance step is `door_plane_from_polygon` under another name — so they live here once.

Deliberately free of `pygame` AND of `Settings` (which imports pygame at module scope). The
pipeline runs headless with no display and must not pull the game's runtime in to project a
point onto an edge; it reaches in with a `sys.path` insert of `Code/`, the way the tests
already do. The dependency only ever points that way: nothing here imports from `tools/`.

Anything returning a `pygame.Rect` or `Surface` stays in `Building.py`.
"""

import math
from collections import namedtuple

# Authored to equal wall thickness / chamber inset on the pyramid. Not read from
# building_walls.py --thickness at runtime: if walls change, update the TMX property.
DEFAULT_DOOR_DEPTH = 160
DEFAULT_DOOR_GAP = 400


# Every number either caller wanted from the same projection. `along` is the distance from
# `p` measured down the edge (building_walls picks the door gap with it); `perpendicular` is
# the off-edge distance both callers minimise over; `closest` is the door plane's origin.
Projection = namedtuple("Projection", "along perpendicular closest tangent")


def centroid(points):
    n = float(len(points))
    return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)


def inward_normal(p, q, centre):
    """Unit normal of edge p->q pointing towards `centre`."""
    ex, ey = q[0] - p[0], q[1] - p[1]
    length = math.hypot(ex, ey)
    nx, ny = -ey / length, ex / length
    mid = ((p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0)
    if (centre[0] - mid[0]) * nx + (centre[1] - mid[1]) * ny < 0:
        nx, ny = -nx, -ny
    return nx, ny


def project_onto_edge(point, p, q):
    """Project `point` onto segment p->q. Clamped to the segment, so a point off the end
    projects to the endpoint rather than past it."""
    ex, ey = q[0] - p[0], q[1] - p[1]
    length = math.hypot(ex, ey)
    ux, uy = ex / length, ey / length
    along = (point[0] - p[0]) * ux + (point[1] - p[1]) * uy
    along = max(0.0, min(length, along))
    closest = (p[0] + ux * along, p[1] + uy * along)
    perpendicular = math.hypot(point[0] - closest[0], point[1] - closest[1])
    return Projection(along, perpendicular, closest, (ux, uy))


def nearest_edge(corners, point):
    """(edge index, Projection) for the edge of `corners` that `point` lies nearest.

    The loop both callers wrote separately: a door is authored as a point near the wall, not
    on it, so which edge it belongs to is decided by perpendicular distance.
    """
    best = None
    for i in range(len(corners)):
        p, q = corners[i], corners[(i + 1) % len(corners)]
        projection = project_onto_edge(point, p, q)
        if best is None or projection.perpendicular < best[1].perpendicular:
            best = (i, projection)
    return best


def arch_quad(origin, inward, tangent, door_gap, door_depth):
    """Door-gap quad: on the door edge, extending inward by `door_depth`."""
    hx = tangent[0] * door_gap / 2.0
    hy = tangent[1] * door_gap / 2.0
    ix = inward[0] * door_depth
    iy = inward[1] * door_depth
    a = (origin[0] - hx, origin[1] - hy)
    b = (origin[0] + hx, origin[1] + hy)
    return [a, b, (b[0] + ix, b[1] + iy), (a[0] + ix, a[1] + iy)]


def door_plane_from_polygon(corners, door_point, door_depth=DEFAULT_DOOR_DEPTH,
                            door_gap=DEFAULT_DOOR_GAP):
    """Project `door_point` onto the nearest edge, and face it at the middle of the building.

    Returns (origin on that edge, inward unit normal, arch quad in world px).

    `inward` is simply the direction from the door to the centroid. It used to be the
    perpendicular of whichever edge the door landed nearest, which is fine on a hand-drawn
    polygon -- that edge is a whole wall -- and meaningless on a SAM-traced outline, where
    it is a six-pixel jagged step pointing wherever the trace wobbled. On pyramid_01 it came
    out 33 degrees off, running ALONG the face rather than into the building, and the carved
    passage, `floor_behind_door` and the arch all inherited that with nothing to catch it.

    Walking at the middle cannot produce a direction that fails to enter the building, which
    is the only property the three callers need. It is not the face normal, so the shortest
    route in from a door near a corner is longer than `door_depth` -- that only bounds how
    deep wedge mode's arch reaches, and wedge is opt-in and unused.
    """
    centre = centroid(corners)
    index, projection = nearest_edge(corners, door_point)
    origin = projection.closest
    inward = _toward(origin, centre)
    if inward is None:                      # door sits on the centroid: nothing to face
        p, q = corners[index], corners[(index + 1) % len(corners)]
        inward = inward_normal(p, q, centre)
    # The arch lies across the way in, so its tangent is square to the normal.
    tangent = (-inward[1], inward[0])
    return origin, inward, arch_quad(origin, inward, tangent, door_gap, door_depth)


def _toward(point, centre):
    """Unit vector from `point` to `centre`, or None if they coincide."""
    dx, dy = centre[0] - point[0], centre[1] - point[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    return (dx / length, dy / length)


def depth_along(point, origin, inward):
    return (point[0] - origin[0]) * inward[0] + (point[1] - origin[1]) * inward[1]


def clip_poly_halfplane(verts, origin, inward, min_depth):
    """Keep the side of `verts` with depth >= `min_depth` (convex)."""
    if not verts:
        return []

    def d(p):
        return depth_along(p, origin, inward)

    def intersect(a, b, da, db):
        denom = db - da
        if abs(denom) < 1e-9:
            return b
        t = (min_depth - da) / denom
        return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))

    out = []
    prev = verts[-1]
    prev_d = d(prev)
    prev_in = prev_d >= min_depth
    for cur in verts:
        cur_d = d(cur)
        cur_in = cur_d >= min_depth
        if cur_in:
            if not prev_in:
                out.append(intersect(prev, cur, prev_d, cur_d))
            out.append(cur)
        elif prev_in:
            out.append(intersect(prev, cur, prev_d, cur_d))
        prev, prev_d, prev_in = cur, cur_d, cur_in
    return out


def inset_polygon(corners, inset):
    """Convex polygon shrunk by `inset`, by offsetting each edge and re-intersecting.

    Convex-only by construction: it intersects consecutive offset edges and trusts the
    result, which a reflex corner turns inside out. Fine for a silhouette; not usable on a
    traced floor plan, which is why the interior emitter walks boundary edges instead.
    """
    centre = centroid(corners)
    lines = []
    for i in range(len(corners)):
        p, q = corners[i], corners[(i + 1) % len(corners)]
        nx, ny = inward_normal(p, q, centre)
        lines.append(((p[0] + nx * inset, p[1] + ny * inset),
                      (q[0] + nx * inset, q[1] + ny * inset)))

    out = []
    for i in range(len(lines)):
        (x1, y1), (x2, y2) = lines[i - 1]
        (x3, y3), (x4, y4) = lines[i]
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(den) < 1e-9:
            out.append(corners[i])
            continue
        a = x1 * y2 - y1 * x2
        b = x3 * y4 - y3 * x4
        out.append(((a * (x3 - x4) - (x1 - x2) * b) / den,
                    (a * (y3 - y4) - (y1 - y2) * b) / den))
    return out
