"""Automatic tests on a traced floor plan. No API calls, so they are free to run on every draw.

Following ``world_levels.checks``: each check returns a number and a verdict and nothing
else. What goes back to the model on a retry is only ever what a person types.

These exist because the generator's only gate was ``check_border``, which asserts byte
equality on the 26% rim outside the chamber. That is a registration check, and registration
was never what failed -- it passes on the shipped asset, which has two unrelated floor plans
meeting at row 1536. Everything that actually went wrong (no floor behind the door, rooms
you cannot reach, a corridor narrower than the player) is a flood fill on a mask, and none
of it was measured.

Erosion is one primitive at three radii. ``dilate_mask`` is the only morphology in the tree,
so eroding is dilating the complement -- no new dependency for the sake of one operator.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..world_levels.geometry import dilate_mask
from .trace import component_report

TILE = 150

# How far inward of the door plane the arch itself runs before the model's paint starts. The
# door polygon is deliberately held out of the editable region (a mask cutting through a
# straddling arch gets it reinvented), so a stretch of non-floor immediately inside the
# threshold is correct, not a fault. Beyond this it is stone where the corridor should be.
MAX_DOOR_GAP_TILES = 1.5
# A door opening onto a cupboard is not an entrance.
MIN_CORRIDOR_DEPTH_TILES = 2.0
# The model was asked to repaint the chamber; this much of it left as masonry means it did
# not do the job, whatever else measures well.
MAX_UNPAINTED = 0.05
# Half-widths for the erosion ladder, in tiles. The player default is deliberately the
# passable half-width rather than the sprite's own hitbox: a corridor one character wide
# survives erosion by half a character as a line, and anything narrower breaks the floor in
# two. Pass the real hitbox if you want the check tighter.
PLAYER_HALF_TILES = 0.5
CORRIDOR_HALF_TILES = 1.0
# Band inside the chamber edge that counts as touching it, when counting openings.
EDGE_BAND_PX = 12
# Minimum area, in square tiles, before a surviving blob counts as a room. Erosion leaves a
# nub wherever two corridors cross, because a junction holds a larger inscribed disk than
# either arm; without this every junction is counted as a room.
MIN_ROOM_TILES_SQ = 1.0
# Below this, a component is trace noise -- a speck of stray paint or a rounding artefact --
# and must not be able to fail a plan on its own.
SPECK_TILES_SQ = 0.05


def erode(mask, radius):
    """Shrink a boolean mask by `radius`. The complement of a dilation of the complement."""
    if radius <= 0:
        return mask.astype(bool)
    return ~dilate_mask(~mask.astype(bool), int(radius))


@dataclass(frozen=True)
class PlanGeometry:
    """Everything the checks read, all canvas-local so nothing here knows about world space."""

    floor: np.ndarray
    chamber: np.ndarray
    silhouette: np.ndarray
    # What the model was actually allowed to paint: the chamber minus the held-out door
    # polygons. Distinct from the chamber, and the distinction matters -- the door hold-out
    # can be two characters deep, so measuring anything from the door plane itself charges
    # the model for pixels it was forbidden to touch.
    editable: np.ndarray = None
    door_origin: tuple = (0, 0)
    door_inward: tuple = (0, 1)
    unpainted_fraction: float = 0.0
    tile: int = TILE
    expected_rooms: int | None = None
    player_half_width: float | None = None
    corridor_half_width: float | None = None

    def tiles(self, px) -> float:
        return round(float(px) / self.tile, 2)

    def area(self, tiles_squared) -> int:
        return int(tiles_squared * self.tile * self.tile)


def unpainted(plan) -> dict:
    """Check zero: did the model repaint the chamber at all?"""
    return {
        "name": "unpainted",
        "fraction": round(plan.unpainted_fraction, 4),
        "limit": MAX_UNPAINTED,
        "passed": plan.unpainted_fraction <= MAX_UNPAINTED,
    }


def floor_behind_door(plan) -> dict:
    """Walk inward from the door plane: how much stone first, then how much floor.

    The failure this catches is the one every draw so far has had -- a corridor that arrives
    near the threshold instead of at it, or masonry painted straight across the back of it.
    """
    limit = int(10 * plan.tile)
    height, width = plan.floor.shape
    paintable = plan.editable if plan.editable is not None else plan.chamber
    gap, depth, seen_floor, entered = None, 0, False, None
    for step in range(limit):
        x = int(round(plan.door_origin[0] + plan.door_inward[0] * step))
        y = int(round(plan.door_origin[1] + plan.door_inward[1] * step))
        if not (0 <= x < width and 0 <= y < height):
            break
        # The walk starts at the door plane, which sits on the silhouette. Between there and
        # the first pixel the model could paint lie the wall rim and the held-out arch, both
        # authored. The gap is counted from where its brush was first allowed, not from the
        # threshold -- otherwise a perfect plan is charged for the building's own wall.
        if entered is None:
            if not paintable[y, x]:
                continue
            entered = step
        if plan.floor[y, x]:
            if not seen_floor:
                gap, seen_floor = step - entered, True
            depth += 1
        elif seen_floor:
            break  # the first floor run is the corridor; stone after it is the far wall
    if gap is None:
        return {
            "name": "floor_behind_door",
            "gap_tiles": None,
            "depth_tiles": 0.0,
            "passed": False,
        }
    return {
        "name": "floor_behind_door",
        "gap_tiles": plan.tiles(gap),
        "gap_limit_tiles": MAX_DOOR_GAP_TILES,
        "depth_tiles": plan.tiles(depth),
        "depth_min_tiles": MIN_CORRIDOR_DEPTH_TILES,
        "passed": (plan.tiles(gap) <= MAX_DOOR_GAP_TILES
                   and plan.tiles(depth) >= MIN_CORRIDOR_DEPTH_TILES),
    }


def floor_connected(plan) -> dict:
    """One floor component. With floor_behind_door passing, this is reachability."""
    report = component_report(plan.floor, min_area=plan.area(SPECK_TILES_SQ))
    return {
        "name": "floor_connected",
        "components": report.count,
        "runner_up_ratio": round(report.runner_up_ratio, 3),
        "passed": report.count == 1,
    }


def one_opening(plan) -> dict:
    """How many places the floor runs out to the chamber edge.

    Anywhere but the door is a second entrance into a solid building. Counted as connected
    components of the floor lying in a thin band inside the chamber boundary, so a single
    wide doorway counts once rather than once per pixel.
    """
    # The edge of what could be painted, not of the chamber: the door hold-out cuts a bite
    # out of the paintable region, and the corridor reaching that bite IS the entrance.
    region = plan.editable if plan.editable is not None else plan.chamber
    band = region & ~erode(region, EDGE_BAND_PX)
    report = component_report(plan.floor & band, min_area=plan.area(SPECK_TILES_SQ))
    return {
        "name": "one_opening",
        "openings": report.count,
        "passed": report.count == 1,
    }


def passable_width(plan) -> dict:
    """Nothing narrower than the player.

    Eroding by the passable half-width leaves a one-character corridor as a line and deletes
    anything tighter -- which breaks the floor into pieces. So the measure is whether the
    eroded floor is still one component, not how thin the thinnest part is.
    """
    radius = plan.player_half_width or PLAYER_HALF_TILES * plan.tile
    report = component_report(erode(plan.floor, radius), min_area=plan.area(SPECK_TILES_SQ))
    return {
        "name": "passable_width",
        "radius_tiles": plan.tiles(radius),
        "components": report.count,
        "passed": report.count == 1,
    }


def room_count(plan) -> dict:
    """Rooms are what survives eroding the corridors away.

    Floor components cannot be the room metric: a dungeon with a corridor is one component,
    which is exactly what floor_connected demands. The two would contradict each other. At a
    radius wider than a corridor's half-width the corridors vanish and the rooms are left.
    """
    radius = plan.corridor_half_width or CORRIDOR_HALF_TILES * plan.tile
    report = component_report(erode(plan.floor, radius), min_area=plan.area(MIN_ROOM_TILES_SQ))
    result = {
        "name": "room_count",
        "radius_tiles": plan.tiles(radius),
        "min_room_tiles_sq": MIN_ROOM_TILES_SQ,
        "rooms": report.count,
    }
    if plan.expected_rooms is None:
        result["skipped"] = "no room count was interviewed"
        result["passed"] = True
        return result
    result["expected"] = plan.expected_rooms
    result["passed"] = report.count == plan.expected_rooms
    return result


CHECKS = (unpainted, floor_behind_door, floor_connected, one_opening, passable_width, room_count)


def run_checks(plan) -> dict:
    results = [check(plan) for check in CHECKS]
    return {
        "checks": results,
        "passed": all(item["passed"] for item in results),
        "failed": [item["name"] for item in results if not item["passed"]],
    }


def score(report) -> tuple:
    """Sort key for ranking draws: fewest failures first, then the soft numbers.

    The sampler is unseeded, so N draws of one prompt differ materially. Picking by eye off
    a contact sheet was the only lever; ranking them by checks that cost nothing turns that
    into throughput.
    """
    by_name = {item["name"]: item for item in report["checks"]}
    depth = by_name.get("floor_behind_door", {}).get("depth_tiles") or 0.0
    return (
        len(report["failed"]),
        by_name.get("unpainted", {}).get("fraction", 1.0),
        -float(depth),
    )


def format_report(report, label: str = "") -> str:
    lines = [f"{label}:" if label else "plan:"]
    for item in report["checks"]:
        if item.get("skipped"):
            lines.append(f"  --  {item['name']}: skipped ({item['skipped']})")
            continue
        detail = ", ".join(
            f"{key}={value}" for key, value in item.items()
            if key not in {"name", "passed", "skipped"}
        )
        lines.append(f"  {'ok' if item['passed'] else 'FAIL'}  {item['name']}: {detail}")
        if item["name"] == "floor_behind_door" and not item["passed"]:
            if item.get("gap_tiles") is None:
                lines.append("      no floor at all on the inward ray -- the door opens onto stone")
            else:
                lines.append("      the corridor does not meet the painted threshold")
        if item["name"] == "one_opening" and item.get("openings", 0) > 1:
            lines.append(
                f"      {item['openings']} places reach the chamber edge; a solid building "
                f"has one")
    return "\n".join(lines)
