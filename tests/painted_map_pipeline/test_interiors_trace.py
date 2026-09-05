"""Tracing a flat-class plan painting into geometry.

The generator these replace could not tell a plan from a picture of stone, because nothing
downstream of the paint ever looked at what was painted. Every assertion here is on a
synthetic image with a known answer, so the trace is pinned before any model draws one.
"""

from __future__ import annotations

import numpy as np

from tools.painted_map_pipeline.interiors.trace import (
    FLOOR_RGB,
    REJECT_DISTANCE,
    SOLID_RGB,
    component_report,
    derive_art_classes,
    partition_with_reject,
    to_world,
    trace_boundaries,
)

SANDSTONE = (182, 150, 104)


def _painted(size=(200, 200)):
    """A canvas of unpainted masonry with a floor bar and a solid surround drawn on it."""
    image = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    image[:, :] = SANDSTONE
    return image


def _all(size=(200, 200)):
    return np.ones((size[1], size[0]), dtype=bool)


def test_unrepainted_masonry_lands_in_the_reject_bucket():
    """The failure region_proposer's partition cannot see: a model that did nothing.

    Nearest-colour with no gate would hand every sandstone pixel to whichever class its
    browns sat closer to, and the plan would score as valid.
    """
    image = _painted()
    image[20:60, 20:180] = FLOOR_RGB
    image[60:100, 20:180] = SOLID_RGB

    partition = partition_with_reject(image, _all())

    assert partition.masks["floor"].sum() == 40 * 160
    assert partition.masks["solid"].sum() == 40 * 160
    # Everything else was left as masonry and must be reported, not assigned.
    assert partition.reject.sum() == 200 * 200 - 2 * 40 * 160
    assert not (partition.masks["floor"] & partition.reject).any()
    assert 0.5 < partition.unpainted_fraction < 0.7


def test_sandstone_is_further_from_both_classes_than_the_gate():
    """The calibration the gate rests on, asserted rather than assumed."""
    for colour in (FLOOR_RGB, SOLID_RGB):
        distance = np.sqrt(sum((a - b) ** 2 for a, b in zip(SANDSTONE, colour)))
        assert distance > REJECT_DISTANCE * 1.3


def test_compression_drift_still_classifies():
    """A flat fill that has been through a resize keeps its class."""
    image = _painted()
    image[20:60, 20:180] = tuple(c + 18 for c in FLOOR_RGB[:2]) + (FLOOR_RGB[2] - 20,)

    partition = partition_with_reject(image, _all())

    assert partition.masks["floor"].sum() == 40 * 160


def test_only_the_considered_region_is_classified():
    image = _painted()
    image[:, :] = FLOOR_RGB
    considered = np.zeros((200, 200), dtype=bool)
    considered[50:100, 50:100] = True

    partition = partition_with_reject(image, considered)

    assert partition.masks["floor"].sum() == 50 * 50
    assert partition.unpainted_fraction == 0.0


def test_component_report_measures_the_runner_up_before_dropping_it():
    """largest_connected_component discards the rest silently; this is what it discarded."""
    mask = np.zeros((100, 100), dtype=bool)
    mask[10:30, 10:30] = True   # 400 px
    mask[60:70, 60:70] = True   # 100 px

    report = component_report(mask)

    assert report.count == 2
    assert report.largest_area == 400
    assert report.runner_up_ratio == 0.25
    assert report.largest[15, 15] and not report.largest[65, 65]


def test_component_report_on_a_single_region_scores_zero():
    mask = np.zeros((100, 100), dtype=bool)
    mask[10:30, 10:30] = True

    report = component_report(mask)

    assert report.count == 1
    assert report.runner_up_ratio == 0.0


def test_component_report_on_an_empty_mask():
    report = component_report(np.zeros((10, 10), dtype=bool))

    assert report.count == 0
    assert report.largest_area == 0
    assert not report.largest.any()


def test_art_classes_partition_the_chamber_exactly():
    """floor / wall / solid must cover the chamber with no overlap: the render pass's
    control image is built from them, and a gap would be an unspecified pixel."""
    chamber = np.zeros((200, 200), dtype=bool)
    chamber[20:180, 20:180] = True
    floor = np.zeros((200, 200), dtype=bool)
    floor[80:120, 80:120] = True

    classes = derive_art_classes(floor, chamber, thickness=10)

    covered = classes["floor"] | classes["wall"] | classes["solid"]
    assert (covered == chamber).all()
    assert not (classes["floor"] & classes["wall"]).any()
    assert not (classes["wall"] & classes["solid"]).any()


def test_wall_is_a_band_of_the_emitter_thickness_around_the_floor():
    chamber = np.ones((200, 200), dtype=bool)
    floor = np.zeros((200, 200), dtype=bool)
    floor[80:120, 80:120] = True

    wall = derive_art_classes(floor, chamber, thickness=10)["wall"]

    assert wall[75, 100]        # 5 px out from the floor edge: inside the band
    assert not wall[65, 100]    # 15 px out: beyond it
    assert not wall[100, 100]   # the floor itself is not wall


def test_wall_never_escapes_the_chamber():
    """Dilation grows outward, and outside the chamber is the exterior's own pixels."""
    chamber = np.zeros((200, 200), dtype=bool)
    chamber[80:120, 80:120] = True
    floor = chamber.copy()

    classes = derive_art_classes(floor, chamber, thickness=20)

    assert not (classes["wall"] & ~chamber).any()


def test_trace_keeps_holes_as_well_as_outers():
    """A pillar standing in a room is a hole in the floor, and has to stop the player."""
    mask = np.zeros((200, 200), dtype=bool)
    mask[20:180, 20:180] = True
    mask[90:110, 90:110] = False

    boundaries = trace_boundaries(mask)

    assert len([b for b in boundaries if not b.is_hole]) == 1
    assert len([b for b in boundaries if b.is_hole]) == 1


def test_trace_returns_every_component_not_just_the_largest():
    mask = np.zeros((200, 200), dtype=bool)
    mask[10:60, 10:60] = True
    mask[120:180, 120:180] = True

    outers = [b for b in trace_boundaries(mask) if not b.is_hole]

    assert len(outers) == 2


def test_trace_simplifies_a_rectangle_to_its_corners():
    mask = np.zeros((200, 200), dtype=bool)
    mask[20:180, 40:160] = True

    boundaries = trace_boundaries(mask)

    assert len(boundaries) == 1
    assert len(boundaries[0].polygon) == 4


def test_trace_drops_specks_below_min_area():
    mask = np.zeros((200, 200), dtype=bool)
    mask[20:180, 20:180] = True
    mask[5:8, 5:8] = True

    assert len(trace_boundaries(mask, min_area=64)) == 1


def test_to_world_offsets_by_the_footprint_origin():
    assert to_world(((0, 0), (10, 5)), (5850, 2690)) == ((5850, 2690), (5860, 2695))
