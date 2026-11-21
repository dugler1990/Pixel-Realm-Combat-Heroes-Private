"""Circle fog geometry — no pygame."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

Point = Tuple[float, float]
Sector = str  # "N" | "E" | "S" | "W"


@dataclass(frozen=True)
class FogCircle:
    cx: float
    cy: float
    r: float

    def contains(self, x: float, y: float) -> bool:
        return self.is_inside(x, y)

    def is_inside(self, x: float, y: float) -> bool:
        dx = x - self.cx
        dy = y - self.cy
        return (dx * dx + dy * dy) < (self.r * self.r)

    def distance(self, x: float, y: float) -> float:
        return math.hypot(x - self.cx, y - self.cy)


def is_inside(circle: FogCircle, x: float, y: float) -> bool:
    return circle.is_inside(x, y)


def sector_of(circle: FogCircle, x: float, y: float) -> Sector:
    """Cardinal sector from circle center to (x, y). Angle 0 = east, CCW."""
    angle = math.atan2(-(y - circle.cy), x - circle.cx)  # screen y down → flip
    # Map to degrees: 0 east, 90 north, ±180 west, -90 south
    deg = math.degrees(angle)
    if -45.0 <= deg < 45.0:
        return "E"
    if 45.0 <= deg < 135.0:
        return "N"
    if deg >= 135.0 or deg < -135.0:
        return "W"
    return "S"


def antipode_inside(circle: FogCircle, x: float, y: float, inset: float) -> Point:
    """Point opposite (x,y) through the center, strictly inside the rim by inset."""
    dx = x - circle.cx
    dy = y - circle.cy
    dist = math.hypot(dx, dy)
    if dist < 1e-9:
        # Degenerate: push east of center.
        dx, dy, dist = 1.0, 0.0, 1.0
    ux, uy = dx / dist, dy / dist
    place_r = max(0.0, circle.r - max(inset, 1e-6))
    return (circle.cx - ux * place_r, circle.cy - uy * place_r)


def pad_hit(circle: FogCircle, x: float, y: float, angle_deg: float, half_width_deg: float) -> bool:
    """True if (x,y) is near the rim and within an angular pad centered at angle_deg (0=E, CCW)."""
    dist = circle.distance(x, y)
    if dist < circle.r * 0.7 or dist > circle.r * 1.15:
        return False
    ang = math.degrees(math.atan2(-(y - circle.cy), x - circle.cx))
    delta = (ang - angle_deg + 180.0) % 360.0 - 180.0
    return abs(delta) <= half_width_deg
