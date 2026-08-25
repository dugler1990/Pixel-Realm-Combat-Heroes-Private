"""Topology-preserving polygon extraction from a label partition.

``partition_to_polygons`` turns an integer label image (0 = outside, 1..N = regions that
already tile a chunk) into one simple polygon per region, guaranteeing the polygons still
tile exactly and cover the whole chunk. The trick is that region borders are decomposed
into shared *arcs* (a boundary between exactly two labels, run between junctions) and each
arc is simplified once, then both neighbouring regions are rebuilt from the same simplified
arc — so adjacent polygons can never drift apart (no gaps, no overlaps).

Coordinates are pixel *corners*: a corner (x, y) sits at the top-left of pixel [row=y,
col=x]; x in [0, W], y in [0, H].
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import uniform_filter

from .models import Point

Node = tuple[int, int]


def _lab(labels: np.ndarray, row: int, col: int) -> int:
    h, w = labels.shape
    if 0 <= row < h and 0 <= col < w:
        return int(labels[row, col])
    return 0


def _majority_smooth(labels: np.ndarray, kernel: int) -> np.ndarray:
    """Smooth region assignment *within* the chunk (kernel-window majority among region
    labels), leaving the chunk footprint (labels>0) exactly unchanged."""
    if kernel <= 1:
        return labels
    values = [int(v) for v in np.unique(labels) if v != 0]
    if len(values) <= 1:
        return labels
    counts = np.stack(
        [uniform_filter((labels == v).astype(np.float32), size=kernel, mode="nearest") for v in values],
        axis=0,
    )
    smoothed = np.asarray(values)[counts.argmax(axis=0)]
    return np.where(labels > 0, smoothed, 0).astype(labels.dtype)


def _douglas_peucker(points: list[Node], tol: float) -> list[Node]:
    """Simplify an open polyline, always keeping the two endpoints."""
    if len(points) < 3:
        return points
    start, end = points[0], points[-1]
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    seg_len = (dx * dx + dy * dy) ** 0.5
    max_dist, index = -1.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if seg_len == 0:
            dist = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
        else:
            dist = abs(dy * px - dx * py + bx * ay - by * ax) / seg_len
        if dist > max_dist:
            max_dist, index = dist, i
    if max_dist <= tol:
        return [start, end]
    left = _douglas_peucker(points[: index + 1], tol)
    right = _douglas_peucker(points[index:], tol)
    return left[:-1] + right


def _boundary_adjacency(labels: np.ndarray):
    """Return adjacency {node: [(neighbour, edge_id, is_outer)]} for every unit corner-edge
    that separates two different labels (skipping outside↔outside)."""
    h, w = labels.shape
    adj: dict[Node, list[tuple[Node, int, bool]]] = {}
    edge_id = 0

    def add(n1: Node, n2: Node, outer: bool):
        nonlocal edge_id
        adj.setdefault(n1, []).append((n2, edge_id, outer))
        adj.setdefault(n2, []).append((n1, edge_id, outer))
        edge_id += 1

    # Vertical edges (x, y)-(x, y+1): separate pixel [y, x-1] (left) and [y, x] (right).
    for y in range(h):
        for x in range(w + 1):
            left, right = _lab(labels, y, x - 1), _lab(labels, y, x)
            if left != right and (left != 0 or right != 0):
                add((x, y), (x, y + 1), left == 0 or right == 0)
    # Horizontal edges (x, y)-(x+1, y): separate pixel [y-1, x] (top) and [y, x] (bottom).
    for y in range(h + 1):
        for x in range(w):
            top, bottom = _lab(labels, y - 1, x), _lab(labels, y, x)
            if top != bottom and (top != 0 or bottom != 0):
                add((x, y), (x + 1, y), top == 0 or bottom == 0)
    return adj


def _trace_arcs(adj: dict[Node, list[tuple[Node, int, bool]]]):
    """Split the boundary graph into arcs at junctions (degree != 2). Returns a list of arcs
    (each a list of nodes) and a map edge_id -> arc_index."""
    degree = {node: len(edges) for node, edges in adj.items()}
    junctions = {node for node, deg in degree.items() if deg != 2}
    arcs: list[list[Node]] = []
    edge_arc: dict[int, int] = {}
    used: set[int] = set()

    def walk(start: Node, first: tuple[Node, int, bool]) -> list[Node]:
        points = [start]
        neighbour, eid, _ = first
        arc_index = len(arcs)
        cur, cur_edge = neighbour, eid
        used.add(eid)
        edge_arc[eid] = arc_index
        points.append(cur)
        while degree.get(cur, 0) == 2:
            nxt = next(e for e in adj[cur] if e[1] != cur_edge)
            neighbour, eid, _ = nxt
            used.add(eid)
            edge_arc[eid] = arc_index
            cur, cur_edge = neighbour, eid
            points.append(cur)
            if cur == start:  # closed loop returning to start junction
                break
        return points

    for junction in junctions:
        for edge in adj[junction]:
            if edge[1] not in used:
                arcs.append([])
                arcs[-1] = walk(junction, edge)
    # Junction-free loops (a region fully enclosed by one other): pick any unused edge.
    for node, edges in adj.items():
        for edge in edges:
            if edge[1] not in used:
                arcs.append([])
                arcs[-1] = walk(node, edge)
    return arcs, edge_arc


def _edge_key(a: Node, b: Node) -> tuple[Node, Node]:
    return (a, b) if a <= b else (b, a)


def _region_on_left(labels: np.ndarray, p0: Node, p1: Node, region: int) -> bool:
    """True if `region` is the pixel on the left of the directed unit edge p0->p1."""
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    lnx, lny = dy, -dx  # left normal in image coords (y down)
    col = int(np.floor(mx + lnx * 0.5))
    row = int(np.floor(my + lny * 0.5))
    return _lab(labels, row, col) == region


def _dedupe_ring(points: list[Node]) -> list[Node]:
    ring: list[Node] = []
    for pt in points:
        if not ring or ring[-1] != pt:
            ring.append(pt)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring.pop()
    return ring


def partition_to_polygons(
    labels: np.ndarray,
    *,
    smooth_kernel: int = 3,
    tolerance: float = 2.0,
    simplify_outer: bool = True,
) -> dict[int, tuple[Point, ...]]:
    """One simple polygon per region label, sharing simplified borders so they tile exactly.

    Returns {region_label: polygon}. A region that vanishes under smoothing is omitted.
    ``tolerance`` is the Douglas-Peucker distance (px): small values only remove the pixel
    staircase and never move a real corner more than that, so the outline follows the shape
    with no big cut-offs. ``simplify_outer=False`` keeps the chunk's outer edge exact.
    """
    labels = _majority_smooth(labels, smooth_kernel)
    region_ids = [int(v) for v in np.unique(labels) if v != 0]
    if not region_ids:
        return {}

    adj = _boundary_adjacency(labels)
    if not adj:
        return {}
    raw_arcs, edge_arc = _trace_arcs(adj)

    # Which two labels each arc separates, and whether it is an outer (chunk-edge) arc.
    arc_pair: list[frozenset[int]] = []
    arc_outer: list[bool] = []
    for arc in raw_arcs:
        a, b = arc[0], arc[1]
        # find the edge id for the first segment to read its labels
        outer = False
        for neighbour, eid, is_outer in adj[a]:
            if neighbour == b:
                outer = is_outer
                break
        # label pair from the two pixels flanking the first edge
        mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        dx, dy = b[0] - a[0], b[1] - a[1]
        nx, ny = dy, -dx
        l1 = _lab(labels, int(np.floor(my + ny * 0.5)), int(np.floor(mx + nx * 0.5)))
        l2 = _lab(labels, int(np.floor(my - ny * 0.5)), int(np.floor(mx - nx * 0.5)))
        arc_pair.append(frozenset({l1, l2}))
        arc_outer.append(outer)

    def build(tolerance: float) -> dict[int, tuple[Point, ...]]:
        simplified: list[list[Node]] = []
        for arc, outer in zip(raw_arcs, arc_outer):
            # Exact outer keeps the chunk boundary (tol 0 still drops collinear points, so a
            # straight edge collapses to its endpoints without cutting real corners).
            tol = 0.0 if (outer and not simplify_outer) else tolerance
            simplified.append(_douglas_peucker(list(arc), tol))

        polygons: dict[int, tuple[Point, ...]] = {}
        for region in region_ids:
            # oriented segments of this region's boundary (region kept on the left)
            segments: list[tuple[Node, Node, list[Node]]] = []
            for index, pair in enumerate(arc_pair):
                if region not in pair:
                    continue
                pts = simplified[index]
                raw = raw_arcs[index]
                if not _region_on_left(labels, raw[0], raw[1], region):
                    pts = pts[::-1]
                segments.append((pts[0], pts[-1], pts))
            if not segments:
                continue
            # chain segments end->start into rings; keep the largest ring
            rings: list[list[Node]] = []
            remaining = segments[:]
            while remaining:
                start, end, pts = remaining.pop(0)
                ring = list(pts)
                guard = 0
                while end != start and guard < len(segments) + 1:
                    guard += 1
                    nxt = next((s for s in remaining if s[0] == end), None)
                    if nxt is None:
                        break
                    remaining.remove(nxt)
                    ring.extend(nxt[2][1:])
                    end = nxt[1]
                rings.append(ring)
            ring = max(rings, key=lambda r: len(_dedupe_ring(r)))
            clean = _dedupe_ring(ring)
            if len(clean) >= 3:
                polygons[region] = tuple((int(x), int(y)) for x, y in clean)
        return polygons

    return build(tolerance)
