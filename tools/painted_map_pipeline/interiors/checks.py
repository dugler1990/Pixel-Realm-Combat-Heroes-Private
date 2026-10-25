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
# In PLAYERS, which is what these are really about. A tile is 2.8 barbs wide, so measuring a
# doorway or a corridor in tiles asks for several players' worth of clearance without ever
# saying so. Every one of these is a game-feel decision rather than a measurement -- how far
# inside the door you should be able to walk before the plan is doing its job -- so they are
# defaults to be argued with, and the plan loop can change them.
MAX_DOOR_GAP_PLAYERS = 3.0        # stone between the door plane and where floor starts
MIN_CORRIDOR_DEPTH_PLAYERS = 4.0  # floor running inward from the doorway
MIN_ROOM_PLAYERS_SQ = 6.0         # footprints before a surviving blob counts as a room
# A door opening onto a cupboard is not an entrance.
MIN_CORRIDOR_DEPTH_TILES = 2.0
# The model was asked to repaint the chamber; this much of it left as masonry means it did
# not do the job, whatever else measures well.
MAX_UNPAINTED = 0.05
# Half-widths for the erosion ladder, in tiles.
#
# PLAYER_HALF_TILES is now only a FALLBACK. The real number comes from `player_size`, which
# measures the widest character on the game's own roster -- 127 px, not the 150 px tile this
# constant assumes. A frame is scaled to a whole tile but the character inside it is smaller,
# so 0.5 demanded ~18% more clearance than any player needs and failed corridors that were
# perfectly walkable.
#
# CORRIDOR_HALF_TILES is deliberately NOT derived from the player. It feeds `room_count`,
# where the entire point is that a room is wider than a corridor; setting it to the player's
# width would make every corridor junction count as a room.
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


# ------------------------------------------------------------------ shape
#
# Did the return land on the mask it was given? Nothing on this path ever asked. The plan and
# render passes send an alpha mask through `image_client.OpenAIImageClient._alpha_mask`, the
# model obeys it approximately, and `paste_back` then composites on the mask regardless -- so
# a return whose outline disagreed with the mask produced black holes in the finished art and
# no number anywhere said so. Measured on pyramid_04, the renders scored 0.80 IoU against the
# 0.970 a mask-obeying call measures at, and 6796 px of the chamber came back literally black.
#
# The measurement itself is `world_levels.checks.footprint` and `coverage`, imported rather
# than reimplemented: they are already the thing that catches this, and a second copy of the
# maths would be free to drift from the picture that illustrates it.

# Below this IoU the return is not the shape it was asked for. Lower than world_levels' own
# gate because an interior legitimately spills: the model paints the doorway hold-out and a
# rim of the surrounding wall, neither of which is an error and both of which count against
# the raw IoU. Shortfall is what actually breaks the art, and `coverage` gates that separately.
MIN_FOOTPRINT_IOU = 0.90

# How much of the mask may come back unpainted. Not zero, unlike world_levels: a level with a
# hole in it poisons its neighbour's padding, while a few hundred stray pixels inside a
# building are absorbed by the composite. Anything approaching a visible wedge is not.
MAX_MISSING_FRACTION = 0.005

# What counts as "painted", in summed RGB. Two numbers, because spill and shortfall are two
# questions and one threshold cannot answer both once the art is legitimately dark.
#
# CONTENT is "did paint land outside the mask", and stays at the world-level 40 for both
# passes. Dropping it to 0 counts the model's own near-black background as spill and sends the
# IoU from 0.80 to 0.67 for renders that had not changed.
#
# MISSING is "did the model leave the mask blank". 40 is right for the plan pass, whose two
# colours are bright and where nothing near-black is ever legitimate. It is wrong for
# stonework: interior stone in shadow sums below 40, so 40 marks correctly painted floor as
# missing. Measured on render_draw1, 3.03% missing at 0 against 8.09% at 24 -- and the 3.03%
# is exactly the black wedges that appear in the composite.
CONTENT_THRESHOLD = 40
PLAN_MISSING_THRESHOLD = 40
RENDER_MISSING_THRESHOLD = 0

# Whether a shape failure ranks a draw down or is only reported. Gating is the point -- a bad
# shape is not a matter of taste -- but it is one name to flip if the checks ever get in the
# way of a hand-picked draw.
SHAPE_GATES = True


def shape_checks(raw, sent_mask, *, minimum: float = MIN_FOOTPRINT_IOU,
                 max_missing: float = MAX_MISSING_FRACTION,
                 content_threshold: int = CONTENT_THRESHOLD,
                 missing_threshold: int = PLAN_MISSING_THRESHOLD) -> list:
    """`footprint` and `coverage` on one draw, in the shape the rest of the report uses.

    `raw` and `sent_mask` are the image the model returned and the mask it was sent, both at
    generation resolution -- never the upscaled or composited versions. Scoring the composite
    would measure our own paste rather than the model's obedience, and would pass every time.

    `footprint` carries the spill and so reads at `content_threshold`; `coverage` carries the
    shortfall and reads at `missing_threshold`. The `missing_px` inside the footprint dict is
    therefore the spill-threshold view of the same thing -- `coverage` is the one to believe,
    and the one the printed report points at.
    """
    from ..world_levels.checks import coverage, footprint

    shape = footprint(raw, sent_mask, minimum=minimum, content_luma_threshold=content_threshold)
    total = max(1, int((np.asarray(sent_mask.convert("L")) > 0).sum()))
    filled = coverage(raw, sent_mask, maximum=int(max_missing * total),
                      content_luma_threshold=missing_threshold)
    if not SHAPE_GATES:
        shape["passed"] = filled["passed"] = True
    return [shape, filled]


def shape_overlay(raw, sent_mask, *, content_threshold: int = CONTENT_THRESHOLD,
                  missing_threshold: int = PLAN_MISSING_THRESHOLD):
    """The draw with its shape error painted on: magenta left black, cyan spilled.

    The same two thresholds the scores used, so the picture and the numbers cannot disagree --
    which is the reason `world_levels.checks` keeps them in one module and this borrows both.
    """
    from ..world_levels.checks import footprint_overlay

    return footprint_overlay(raw, sent_mask, content_luma_threshold=content_threshold,
                             missing_luma_threshold=missing_threshold)


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
    # The player this plan is judged against, in px. When set, the door and room thresholds
    # are derived from it rather than from the tile -- see the *_PLAYERS constants.
    player_width: float | None = None
    player_height: float | None = None

    def tiles(self, px) -> float:
        return round(float(px) / self.tile, 2)

    def area(self, tiles_squared) -> int:
        return int(tiles_squared * self.tile * self.tile)

    def door_gap_limit(self) -> float:
        """Stone allowed between the door plane and the floor."""
        if self.player_width:
            return MAX_DOOR_GAP_PLAYERS * self.player_width
        return MAX_DOOR_GAP_TILES * self.tile

    def corridor_depth_min(self) -> float:
        """Floor that must run inward from the doorway."""
        if self.player_height:
            return MIN_CORRIDOR_DEPTH_PLAYERS * self.player_height
        return MIN_CORRIDOR_DEPTH_TILES * self.tile

    def room_area_min(self) -> int:
        """Area before a blob counts as a room rather than a junction nub."""
        if self.player_width and self.player_height:
            return int(MIN_ROOM_PLAYERS_SQ * self.player_width * self.player_height)
        return self.area(MIN_ROOM_TILES_SQ)


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
    gap_limit = plan.door_gap_limit()
    depth_min = plan.corridor_depth_min()
    return {
        "name": "floor_behind_door",
        "gap_tiles": plan.tiles(gap),
        # In px too: the emitter grows its doorway zone by exactly this, so whatever stretch
        # of stone this check accepted between the door and the floor is never walled.
        "gap_px": int(gap),
        "gap_limit_tiles": round(gap_limit / plan.tile, 2),
        "gap_limit_px": int(round(gap_limit)),
        "depth_tiles": plan.tiles(depth),
        "depth_min_tiles": round(depth_min / plan.tile, 2),
        "depth_min_px": int(round(depth_min)),
        "sized_by": "player" if plan.player_width else "tile",
        "passed": gap <= gap_limit and depth >= depth_min,
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
    from .prompt import MIN_CORRIDOR_PLAYERS

    # Half of the MINIMUM walkable width, not half a player: a corridor exactly one person
    # wide is one you get wedged in, and the eroded floor has to survive as one piece with
    # something to spare.
    measured = plan.player_half_width
    radius = (measured * MIN_CORRIDOR_PLAYERS) if measured else PLAYER_HALF_TILES * plan.tile
    report = component_report(erode(plan.floor, radius), min_area=plan.area(SPECK_TILES_SQ))
    return {
        "name": "passable_width",
        "radius_tiles": plan.tiles(radius),
        # What it demanded and where that came from. A gate that fails a plan should be able
        # to say which number it used, or the only way to find out is to read the source.
        "radius_px": int(round(radius)),
        "source": "measured player" if measured else "PLAYER_HALF_TILES fallback",
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
    room_min = plan.room_area_min()
    report = component_report(erode(plan.floor, radius), min_area=room_min)
    result = {
        "name": "room_count",
        "radius_tiles": plan.tiles(radius),
        "min_room_px_sq": room_min,
        "sized_by": "player" if plan.player_width else "tile",
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


def run_checks(plan, extra=()) -> dict:
    """Every geometric check, plus any already-computed ones handed in.

    `extra` is for checks that need something `PlanGeometry` does not carry -- the shape pair
    needs the raw return and the mask that was sent, which are generation-resolution images
    rather than canvas-local masks. Appending them here rather than keeping a second report
    means one verdict, one ranking, and one printed block.
    """
    results = [check(plan) for check in CHECKS] + list(extra)
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
        # Spill and shortfall are different failures with different remedies, so say which.
        if item["name"] == "footprint" and not item["passed"]:
            lines.append(
                f"      the return is not the shape it was given: {item['spilled_px']} px "
                f"painted outside the mask, {item['missing_px']} px of the mask left blank "
                f"(cut_iou {item['cut_iou']} -- what it scores once the spill is trimmed)")
            lines.append("      [r1] resends this draw with its shape error marked")
        if item["name"] == "coverage" and not item["passed"]:
            lines.append(
                f"      {item['missing_px']} px of the mask came back unpainted; the paste "
                f"writes those in as black. Nothing downstream can invent them -- redraw")
    return "\n".join(lines)
