"""The interior walkthrough, offline: spec, identify, emit, and one end-to-end pass.

Everything here runs with no API key and no model. That is the point of the synthetic plan
provider -- the emitter, the checks and the geometry can be exercised at the real building's
scale, against its real doorway, for free.
"""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from tools.painted_map_pipeline.interiors import emit as emit_mod
from tools.painted_map_pipeline.interiors import identify as identify_mod
from tools.painted_map_pipeline.interiors import plan as plan_mod
from tools.painted_map_pipeline.interiors import spec as spec_mod

MAP = Path("levels/Frostreach/sunspine_7x6_play/map.tmx")
BUILDING = "great_pyramid"

pytestmark = pytest.mark.skipif(not MAP.exists(), reason="sunspine level not in this checkout")


@pytest.fixture(scope="module")
def spec():
    return spec_mod.from_map(MAP, BUILDING, object_prompt="pyramid",
                             entrance_prompt="dark doorway", intent="a crypt", rooms=3)


@pytest.fixture(scope="module")
def plan(spec):
    return plan_mod.synthetic_plan(spec)


# ---------------------------------------------------------------- spec

def test_spec_computes_the_scale_rather_than_asking_for_it(spec):
    """Every number a person would otherwise type into a prompt comes from the building."""
    assert spec.size == (3600, 3140)
    assert spec.tiles == (24.0, 20.9)
    assert 390 < spec.door_width < 410  # the authored 400 px door gap


def test_spec_resolves_the_door_plane_through_the_games_own_call(spec):
    """The threshold, the collision gap and the roof split are one piece of geometry."""
    assert spec.door_origin is not None
    assert spec.arch_quad
    # The pyramid's door is on the lower-right face, so inward points up and left.
    assert spec.door_inward[0] < 0 and spec.door_inward[1] < 0


def test_spec_round_trips(spec, tmp_path):
    path = spec.save(tmp_path / "interior.json")
    loaded = spec_mod.InteriorSpec.load(path)

    assert loaded.building == spec.building
    assert loaded.door_origin == spec.door_origin
    assert loaded.silhouette == spec.silhouette
    assert loaded.rooms == 3


def test_a_spec_from_another_schema_is_refused_not_guessed_at(tmp_path):
    path = tmp_path / "old.json"
    path.write_text('{"schema_version": 0, "building": "x"}', encoding="utf-8")

    with pytest.raises(ValueError, match="re-run the interview"):
        spec_mod.InteriorSpec.load(path)


# ---------------------------------------------------------------- identify

def test_identify_reads_the_authored_polygon_offline():
    found = identify_mod.identify(MAP, BUILDING, "pyramid", "dark doorway")

    assert found.source == "tmx"
    assert len(found.silhouette) == 4
    assert found.door_point == (8430.0, 4970.0)


def test_identify_says_so_when_there_is_nothing_to_check_against():
    """The gate only exists where the collision pass has already run. It must report that
    rather than silently passing."""
    found = identify_mod.identify(MAP, BUILDING, "pyramid")

    assert found.iou is None
    assert any("no SAM3 obstacles" in note for note in found.notes)


def test_polygon_iou_scores_agreement():
    square = ((0, 0), (100, 0), (100, 100), (0, 100))
    shifted = ((50, 0), (150, 0), (150, 100), (50, 100))
    far = ((900, 900), (1000, 900), (1000, 1000), (900, 1000))

    assert identify_mod.polygon_iou(square, [square]) > 0.98
    assert 0.2 < identify_mod.polygon_iou(square, [shifted]) < 0.45
    assert identify_mod.polygon_iou(square, [far]) == 0.0
    assert identify_mod.polygon_iou(square, []) is None


def test_an_unknown_identify_provider_names_the_ones_that_exist():
    with pytest.raises(ValueError, match="offline default"):
        identify_mod.identify(MAP, BUILDING, "pyramid", provider="magic")


# ---------------------------------------------------------------- plan

def test_the_synthetic_plan_passes_every_check_at_the_real_scale(plan):
    """The offline provider exists to prove the plumbing end to end, so it has to be a plan
    that would actually be accepted -- not merely one that traces."""
    assert plan.passed, plan.failed


def test_the_plan_pass_runs_far_below_the_size_cap():
    """Loop A is cheap because of resolution, not because flat colour is cheap."""
    width, height = plan_mod.plan_size((3600, 3140))

    assert max(width, height) == plan_mod.PLAN_EDGE
    assert width % 16 == 0 and height % 16 == 0
    assert width * height < 3_000_000


def test_art_classes_cover_the_chamber_and_the_wall_band_is_the_emitter_thickness(plan):
    covered = plan.classes["floor"] | plan.classes["wall"] | plan.classes["solid"]

    assert (covered == plan.chamber).all()
    assert plan.classes["wall"].any()


def test_the_control_image_is_three_flat_colours_inside_the_chamber(plan):
    """Flat and unmixed, so the render pass has no ambiguity about what a pixel means.
    Outside the chamber it is black -- that region is the exterior's own art, not a class."""
    image = np.asarray(plan_mod.control_image(plan))

    assert len(np.unique(image[plan.chamber], axis=0)) == 3
    assert not image[~plan.chamber].any()


# ---------------------------------------------------------------- emit

def test_the_chamber_comes_from_the_trace_not_from_an_inset(plan):
    """The whole reason art and collision could never agree: an inset of the silhouette
    describes 74% of a solid pyramid as room. A traced chamber follows the dungeon."""
    chamber = emit_mod.chamber_from_plan(plan)

    assert len(chamber) > 4  # the authored one is a four-vertex diamond


def test_the_chamber_stays_inside_the_silhouette(plan, spec):
    """`build_masks` asserts this; if it ever fails the interior spills onto the desert."""
    from tools.painted_map_pipeline.world_levels.masks import rasterize_polygon

    chamber = emit_mod.chamber_from_plan(plan)
    local = tuple((x - spec.origin[0], y - spec.origin[1]) for x, y in chamber)
    inside = np.asarray(rasterize_polygon(spec.size, local)) > 0

    assert not (inside & ~plan.silhouette).any()


def test_the_emitter_handles_a_non_convex_floor(plan):
    """`wall_segments` tiles one convex ring with one gap; a corridor with rooms off it is
    neither, which is why this walks traced boundaries instead."""
    quads = emit_mod.wall_quads(plan)

    assert len(quads) > 20
    assert all(len(quad) == 4 for quad in quads)


def test_wall_segments_stay_short_so_push_out_stays_local(plan):
    """Push-out direction comes from the obstacle AABB centre, not the contact point, so a
    long segment ejects anyone touching its end sideways instead of away."""
    import math

    for quad in emit_mod.wall_quads(plan):
        length = math.hypot(quad[1][0] - quad[0][0], quad[1][1] - quad[0][1])
        assert length <= emit_mod.SEGMENT_LENGTH + 1.0


def test_rooms_match_what_the_check_counted(plan):
    counted = next(c for c in plan.report["checks"] if c["name"] == "room_count")

    assert len(emit_mod.rooms(plan)) == counted["rooms"]


# ---------------------------------------------------------------- writing

def _map_copy(tmp_path):
    target = tmp_path / "map.tmx"
    shutil.copyfile(MAP, target)
    return target


def _names(map_path):
    """Named objects only -- the painted-ground image object carries no name."""
    root = ET.parse(map_path).getroot()
    return [o.get("name") for group in root.iter("objectgroup")
            for o in group.findall("object") if o.get("name")]


def test_writing_a_plan_replaces_the_generated_geometry(plan, tmp_path):
    target = _map_copy(tmp_path)
    before = [n for n in _names(target) if n.startswith("great_pyramid_wall")]
    assert before, "the fixture map should already carry generated walls"

    result = emit_mod.write_plan(plan, target)
    after = [n for n in _names(target) if n.startswith("great_pyramid_wall")]

    assert len(after) == result["walls"] != len(before)


def test_writing_is_idempotent(plan, tmp_path):
    """Re-running must replace its own objects, not stack another set on top."""
    target = _map_copy(tmp_path)
    emit_mod.write_plan(plan, target)
    once = _names(target)
    emit_mod.write_plan(plan, target)

    assert _names(target) == once


def test_hand_authored_objects_survive_a_write(plan, tmp_path):
    target = _map_copy(tmp_path)
    emit_mod.write_plan(plan, target)

    assert "great_pyramid" in _names(target)
    assert "great_pyramid_door" in _names(target)


def test_object_ids_stay_unique_after_a_write(plan, tmp_path):
    target = _map_copy(tmp_path)
    emit_mod.write_plan(plan, target)
    root = ET.parse(target).getroot()
    ids = [o.get("id") for group in root.iter("objectgroup")
           for o in group.findall("object")]

    assert len(ids) == len(set(ids))
