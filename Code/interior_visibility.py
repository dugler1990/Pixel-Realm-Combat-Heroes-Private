"""What you can see inside a building.

Walls block sight, and nothing else does. The walls are the building's stone -- everything
inside it a body cannot stand on -- which the interior pipeline writes into the map as
`sight_of` loops. A room and a corridor are just floor; nothing here knows either.

From the camera subject's feet a ray goes out a hair either side of every wall corner in
reach, and all round the rim. Each stops `band` px past the first wall it meets, so the
face of the wall you look at is lit, but never past that wall's far side, so a thin wall
does not light the room behind it. The stopping points, in angle order, outline everything
the feet can see straight across to: a fan of triangles from the feet.

The camera draws the chamber black and the interior again through that fan, and leaves out
any body whose feet the fan does not cover. The fan is recast only when the feet move;
drawing it uploads nothing.
"""

import math
from bisect import bisect_right

import numpy as np
import pygame

from Settings import INTERIOR_SIGHT_RADIUS


FOG_RGBA = (0, 0, 0, 255)
# Feet this far from where the fan was cast from cast it again.
_RECAST_PX = 6
# Rays round the rim, for where no wall is in reach: 4 degrees apart, which at the default
# radius is under a pixel off the circle.
_RIM_RAYS = 90
# Radians either side of a wall corner: one ray grazes past it, the other stops on the wall.
_GRAZE = 1e-4


def walls_from_loops(loops) -> np.ndarray:
    """Closed loops of (x, y) points -> one (x0, y0, x1, y1) row per edge."""
    rows = []
    for loop in loops:
        points = np.asarray(loop, dtype=np.float64).reshape(-1, 2)
        if len(points) >= 2:
            rows.append(np.hstack([points, np.roll(points, -1, axis=0)]))
    return np.vstack(rows) if rows else np.zeros((0, 4))


def _in_reach(a, b, radius):
    """The walls from `a` to `b` (relative to the origin) some part of which is in reach."""
    e = b - a
    length2 = np.einsum("ij,ij->i", e, e)
    along = -np.einsum("ij,ij->i", a, e) / np.where(length2 > 0, length2, 1.0)
    nearest = a + e * np.clip(along, 0.0, 1.0)[:, None]
    keep = np.einsum("ij,ij->i", nearest, nearest) <= radius * radius
    return a[keep], b[keep]


def _ray_ranges(angles, a, b):
    """For each wall, the run of rays (indices into sorted `angles`) pointing at it.

    A wall seen from the origin covers an arc of directions under half a turn, so only the
    rays in that arc can meet it -- a handful per wall, where testing every ray against
    every wall was the whole cost. An arc across the seam at +-pi is two runs.
    """
    ta = np.arctan2(a[:, 1], a[:, 0])
    tb = np.arctan2(b[:, 1], b[:, 0])
    lo, hi = np.minimum(ta, tb), np.maximum(ta, tb)
    seam = hi - lo > math.pi
    margin = 2 * _GRAZE
    wall = np.arange(len(a))
    plain = ~seam
    owners = [wall[plain], wall[seam], wall[seam]]
    starts = [np.searchsorted(angles, lo[plain] - margin, "left"),
              np.searchsorted(angles, hi[seam] - margin, "left"),
              np.zeros(int(seam.sum()), dtype=np.intp)]
    stops = [np.searchsorted(angles, hi[plain] + margin, "right"),
             np.full(int(seam.sum()), len(angles), dtype=np.intp),
             np.searchsorted(angles, lo[seam] + margin, "right")]
    owners, starts, stops = (np.concatenate(parts) for parts in (owners, starts, stops))
    counts = np.maximum(stops - starts, 0)
    first_of_run = np.cumsum(counts) - counts
    walls = np.repeat(owners, counts)
    rays = np.arange(int(counts.sum())) - np.repeat(first_of_run - starts, counts)
    return rays, walls


def sight_ring(origin, walls, radius, band=0.0):
    """The fan `origin` sees, as (ring, angles): one point per ray, in angle order.

    `walls` is (N, 4) segments in the same px as `origin`. A ray stops `band` past the
    first wall it meets, never past the second -- that wall's far side -- and never past
    `radius`.
    """
    ox, oy = float(origin[0]), float(origin[1])
    a, b = _in_reach(walls[:, 0:2] - (ox, oy), walls[:, 2:4] - (ox, oy), float(radius))
    angles = np.linspace(-math.pi, math.pi, _RIM_RAYS, endpoint=False)
    if len(a):
        corners = np.vstack([a, b])
        corners = corners[np.einsum("ij,ij->i", corners, corners) <= radius * radius]
        toward = np.arctan2(corners[:, 1], corners[:, 0])
        angles = np.concatenate([angles, toward - _GRAZE, toward + _GRAZE])
    # Wrapped into [-pi, pi) and sorted, which is the order `sees` bisects.
    angles = np.unique((angles + math.pi) % (2 * math.pi) - math.pi)
    dx, dy = np.cos(angles), np.sin(angles)
    reach = np.full(len(angles), float(radius))
    if len(a):
        ray, wall = _ray_ranges(angles, a, b)
        # origin + t*d = a + s*e, for each ray and the walls it points at.
        ax, ay = a[wall, 0], a[wall, 1]
        ex, ey = b[wall, 0] - ax, b[wall, 1] - ay
        rx, ry = dx[ray], dy[ray]
        den = rx * ey - ry * ex
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (ax * ey - ay * ex) / den
            s = (ax * ry - ay * rx) / den
        hit = (den != 0) & (t > 0) & (s >= 0) & (s <= 1)
        ray, t = ray[hit], t[hit]
        # The nearest two hits on each ray: sorted by ray, then by distance along it.
        order = np.lexsort((t, ray))
        ray, t = ray[order], t[order]
        lead = np.flatnonzero(np.r_[True, ray[1:] != ray[:-1]]) if len(ray) else ray
        first = np.full(len(angles), np.inf)
        first[ray[lead]] = t[lead]
        second = np.full(len(angles), np.inf)
        paired = lead[(lead + 1 < len(ray))]
        paired = paired[ray[paired + 1] == ray[paired]]
        second[ray[paired]] = t[paired + 1]
        reach = np.minimum(np.minimum(first + band, second), reach)
    return np.column_stack([ox + dx * reach, oy + dy * reach]), angles


def _black_chamber(chamber_rect, chamber_mask):
    fog = pygame.Surface(chamber_rect.size, pygame.SRCALPHA)
    if chamber_mask is None:
        fog.fill(FOG_RGBA)
        return fog
    black = chamber_mask.to_surface(setcolor=FOG_RGBA, unsetcolor=(0, 0, 0, 0))
    fog.blit(black, (0, 0))
    return fog


class InteriorSight:
    """One building's walls, and the fan the camera subject sees them from."""

    def __init__(self, chamber_rect, chamber_mask, loops, band=0.0, radius=INTERIOR_SIGHT_RADIUS):
        self.walls = walls_from_loops(loops)
        self.band = float(band)
        self.radius = float(radius)
        # The chamber in black, which the fan is drawn over. Built once, uploaded once.
        self.black_rect = pygame.Rect(chamber_rect)
        self.black = _black_chamber(chamber_rect, chamber_mask)
        self.origin = None
        self.ring = None
        self._angles = None
        self._relative = None

    @property
    def active(self):
        return self.ring is not None

    def reveal_from(self, point):
        """Cast the fan from `point`, unless the current one was cast from near it."""
        if self.origin is not None and math.hypot(
                point[0] - self.origin[0], point[1] - self.origin[1]) < _RECAST_PX:
            return
        self.origin = (float(point[0]), float(point[1]))
        self.ring, angles = sight_ring(self.origin, self.walls, self.radius, self.band)
        self._angles = angles.tolist()
        self._relative = (self.ring - self.origin).tolist()

    def hide(self):
        self.origin = self.ring = self._angles = self._relative = None

    def sees(self, point):
        """Is `point` in the fan? Tested against the same triangles the camera draws."""
        if self.ring is None:
            return False
        px, py = point[0] - self.origin[0], point[1] - self.origin[1]
        if px == 0 and py == 0:
            return True
        i = bisect_right(self._angles, math.atan2(py, px))
        x0, y0 = self._relative[i - 1]
        x1, y1 = self._relative[i % len(self._relative)]
        # Inside when on the feet's side of the triangle's far edge, or on it.
        point_side = (x1 - x0) * (py - y0) - (y1 - y0) * (px - x0)
        feet_side = (x1 - x0) * -y0 - (y1 - y0) * -x0
        return point_side * feet_side >= 0
