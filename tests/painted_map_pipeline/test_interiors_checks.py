"""The layout checks, against synthetic plans with known answers.

Each bad plan here is a failure the shipped generator actually produced and could not see,
because its only gate was byte equality on the rim. A small tile (20 px) keeps the masks
fast; every check is tile-relative, so the numbers mean the same thing at 150.
"""

from __future__ import annotations

import numpy as np

from tools.painted_map_pipeline.interiors.checks import (
    PlanGeometry,
    erode,
    floor_behind_door,
    floor_connected,
    one_opening,
    passable_width,
    room_count,
    run_checks,
    score,
    unpainted,
)

TILE = 20
SIZE = 400
CHAMBER = (40, 360)
DOOR_ORIGIN = (200, 40)
DOOR_INWARD = (0, 1)


def _blank():
    return np.zeros((SIZE, SIZE), dtype=bool)


def _chamber():
    mask = _blank()
    mask[CHAMBER[0]:CHAMBER[1], CHAMBER[0]:CHAMBER[1]] = True
    return mask


def _good_floor():
    """A corridor in from the door with a room either side, each joined by a doorway.

    The rooms are walled off from the corridor and connect through a 30 px gap rather than
    abutting it over their full height. That is how the layout is actually specified -- a
    room open along its whole side is one wide hall, and erosion would (correctly) report
    the three spaces as one.
    """
    floor = _blank()
    floor[45:255, 185:216] = True    # corridor, 31 px wide, starting 5 px inside the door
    floor[150:250, 90:176] = True    # room, left, walled off from the corridor
    floor[185:215, 175:186] = True   # its doorway
    floor[150:250, 225:311] = True   # room, right
    floor[185:215, 215:226] = True   # its doorway
    return floor


def _plan(floor=None, **kwargs):
    return PlanGeometry(
        floor=_good_floor() if floor is None else floor,
        chamber=_chamber(),
        silhouette=np.ones((SIZE, SIZE), dtype=bool),
        door_origin=DOOR_ORIGIN,
        door_inward=DOOR_INWARD,
        tile=TILE,
        **kwargs,
    )


# --------------------------------------------------------------------- the good plan

def test_a_sound_plan_passes_every_check():
    report = run_checks(_plan(expected_rooms=2))

    assert report["passed"], report["failed"]


def test_rooms_are_what_survives_eroding_the_corridors_away():
    """The metric floor components structurally cannot provide: the good plan is ONE
    component by design, and still has two rooms."""
    assert floor_connected(_plan())["components"] == 1
    assert room_count(_plan())["rooms"] == 2


# --------------------------------------------------------------------- door continuity

def test_stone_behind_the_door_fails():
    """The failure in every draw so far: the corridor arrives near the threshold, not at it."""
    floor = _good_floor()
    floor[:150, :] = False  # corridor pulled back well inside

    result = floor_behind_door(_plan(floor))

    assert not result["passed"]
    assert result["gap_tiles"] > 1.5


def test_no_floor_at_all_on_the_inward_ray_fails():
    result = floor_behind_door(_plan(_blank()))

    assert not result["passed"]
    assert result["gap_tiles"] is None
    assert result["depth_tiles"] == 0.0


def test_a_door_opening_onto_a_cupboard_fails():
    floor = _blank()
    floor[45:70, 185:216] = True  # 25 px deep: 1.25 tiles, under the 2.0 minimum

    result = floor_behind_door(_plan(floor))

    assert not result["passed"]
    assert result["depth_tiles"] < 2.0


def test_the_held_out_arch_is_not_counted_as_a_gap():
    """A stretch of non-floor just inside the threshold is the door polygon held out of the
    editable region, which is deliberate -- not a fault."""
    result = floor_behind_door(_plan())

    assert result["gap_tiles"] == 0.25
    assert result["passed"]


# --------------------------------------------------------------------- reachability

def test_an_unreachable_room_fails():
    floor = _good_floor()
    floor[150:250, 320:350] = True  # a room touching nothing

    result = floor_connected(_plan(floor))

    assert not result["passed"]
    assert result["components"] == 2
    assert result["runner_up_ratio"] > 0


# --------------------------------------------------------------------- one way in

def test_a_second_entrance_fails():
    floor = _good_floor()
    floor[150:250, 41:106] = True  # a room run out to the chamber's left edge

    result = one_opening(_plan(floor))

    assert not result["passed"]
    assert result["openings"] == 2


def test_the_good_plan_reaches_the_chamber_edge_exactly_once():
    assert one_opening(_plan())["openings"] == 1


# --------------------------------------------------------------------- width

def test_a_corridor_narrower_than_the_player_fails():
    """Eroding by the passable half-width deletes it, which breaks the floor in two."""
    floor = _good_floor()
    floor[45:255, 185:216] = False
    floor[45:255, 197:203] = True  # 6 px: well under one character

    result = passable_width(_plan(floor))

    assert not result["passed"]
    assert result["components"] > 1


def test_the_good_plan_stays_one_piece_under_player_erosion():
    assert passable_width(_plan())["passed"]


# --------------------------------------------------------------------- check zero

def test_a_chamber_left_as_masonry_fails_check_zero():
    assert not unpainted(_plan(unpainted_fraction=0.42))["passed"]
    assert unpainted(_plan(unpainted_fraction=0.01))["passed"]


# --------------------------------------------------------------------- room count

def test_a_corridor_junction_is_not_counted_as_a_room():
    """A crossing holds a larger inscribed disk than either arm, so eroding the corridors
    away leaves a nub behind at every junction. Unfiltered, each one scores as a room."""
    floor = _blank()
    floor[100:300, 190:211] = True  # vertical arm
    floor[190:211, 100:300] = True  # horizontal arm, crossing it

    assert room_count(_plan(floor))["rooms"] == 0


def test_room_count_is_skipped_when_none_was_interviewed():
    result = room_count(_plan())

    assert result["skipped"]
    assert result["passed"]


def test_room_count_disagreeing_with_the_interview_fails():
    result = room_count(_plan(expected_rooms=5))

    assert not result["passed"]
    assert result["rooms"] == 2


# --------------------------------------------------------------------- primitives

def test_erode_is_the_complement_of_a_dilated_complement():
    mask = _blank()
    mask[100:200, 100:200] = True

    shrunk = erode(mask, 10)

    assert shrunk[110, 110] and not shrunk[105, 105]
    assert shrunk.sum() < mask.sum()


def test_erode_by_zero_is_a_no_op():
    mask = _good_floor()

    assert (erode(mask, 0) == mask).all()


# --------------------------------------------------------------------- ranking

def test_ranking_puts_the_sound_plan_first():
    """N draws of one prompt differ materially on an unseeded sampler. Sorting them by
    checks that cost nothing is the cheapest quality lever available."""
    good = run_checks(_plan(expected_rooms=2))
    broken = run_checks(_plan(_blank(), expected_rooms=2))
    half = run_checks(_plan(unpainted_fraction=0.5, expected_rooms=2))

    ranked = sorted([broken, half, good], key=score)

    assert ranked[0] is good
    assert ranked[-1] is broken
