"""The walls hug the floor they were given, and a refusal leaves you at the gate.

pyramid_01's three-room draw passed every check -- floor right up to the painted door -- and
the build then died on a traceback in `assert_passage_open`. Two faults, both pinned here:

The emitter laid wall blocks along the floor's outline traced at 1% of its perimeter. Rooms
joined by corridors are one contour, so that was 145 px, wider than any corridor: the walls
ran across every room and the entrance corridor. Walls are now the strip round the walkable
ground itself, so they cannot leave its edge.

The refusal was not caught. It is a ValueError out of `write_plan`, two calls below a gate,
so the session ended with every draw still unchosen. A refusal now says why and leaves you
at the decision that led to it.

No map: the spec is built here, because nothing under test reads one.
"""

from __future__ import annotations

import argparse
import math
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image

from tools.painted_map_pipeline.image_client import ImageClientError
from tools.painted_map_pipeline.interiors import art as art_mod
from tools.painted_map_pipeline.interiors import cli as cli_mod
from tools.painted_map_pipeline.interiors import emit as emit_mod
from tools.painted_map_pipeline.interiors import floor as floor_mod
from tools.painted_map_pipeline.interiors import plan as plan_mod
from tools.painted_map_pipeline.interiors import render as render_mod
from tools.painted_map_pipeline.interiors.checks import erode
from tools.painted_map_pipeline.interiors.plan import door_mask, geometry_masks, trace_plan_from_mask
from tools.painted_map_pipeline.interiors.spec import InteriorSpec
from tools.painted_map_pipeline.world_levels.geometry import dilate_mask
from tools.painted_map_pipeline.world_levels.masks import rasterize_polygon

# Narrower than the 1% tolerance the old tracer used on a floor this size, which is the case
# that broke: the corridor vanished into the simplification. 1.5 people, the prompt's floor.
CORRIDOR = 80
# The way in is wider: `one_opening` drops anything under 1125 px in its 12 px edge band as a
# speck, so a mouth narrower than ~94 px is "no opening at all".
ENTRANCE = 110
# Half a room. `room_count` erodes by a whole tile and wants 16.5k px left, so a room under
# ~430 px across does not count as one.
ROOM = 240
# Pixels of give at an edge: the 1 px outline tolerance, plus one for the polygon fill.
SLACK = 2


WALL = 100
DOOR_GAP = 180.0


def _spec(tmp_path) -> InteriorSpec:
    """A diamond building with its door in the middle of the lower-right face, and the
    chamber `art.chamber_from` derives: inset by the wall, with the passage carved to the door.
    """
    centre = (1800.0, 1500.0)
    silhouette = ((1800.0, 40.0), (3560.0, 1500.0), (1800.0, 2960.0), (40.0, 1500.0))
    door_origin = (2680.0, 2230.0)
    dx, dy = centre[0] - door_origin[0], centre[1] - door_origin[1]
    length = math.hypot(dx, dy)
    inward = (dx / length, dy / length)
    tangent = (-inward[1], inward[0])

    def at(across, deep):
        return (door_origin[0] + tangent[0] * across + inward[0] * deep,
                door_origin[1] + tangent[1] * across + inward[1] * deep)

    size = (3600, 3000)
    chamber = art_mod.chamber_from(silhouette, size, WALL, door_point=door_origin,
                                   door_inward=inward, door_gap=DOOR_GAP)
    return InteriorSpec(
        building="test_pyramid", map_path=str(tmp_path / "map.tmx"), origin=(5000, 3000),
        size=size, silhouette=silhouette, chamber=chamber,
        doors=((at(-90, -30), at(90, -30), at(90, 160), at(-90, 160)),),
        roof_image="", interior_image="", door_origin=door_origin, door_inward=inward,
        rooms=3, wall=WALL, door_gap=DOOR_GAP)


def _point(v):
    return tuple(int(round(c)) for c in v)


def _three_rooms(spec):
    """Three rooms off a hub, each on a corridor narrower than the old tolerance, all one
    contour -- the shape of pyramid_01's draw."""
    silhouette, chamber, editable = geometry_masks(spec)
    floor = np.zeros(chamber.shape, np.uint8)
    door, inward = np.asarray(spec.door_origin), np.asarray(spec.door_inward)
    tangent = np.asarray([-inward[1], inward[0]])
    hub = door + inward * 900
    cv2.line(floor, _point(door), _point(hub), 1, ENTRANCE)
    for end in (hub + tangent * 650, hub - tangent * 650, hub + inward * 650):
        cv2.line(floor, _point(hub), _point(end), 1, CORRIDOR)
        cv2.rectangle(floor, _point(end - ROOM), _point(end + ROOM), 1, -1)
    return trace_plan_from_mask(floor.astype(bool) & editable, spec, silhouette, chamber,
                                editable)


def _raster(spec, polygons):
    canvas = np.zeros((spec.size[1], spec.size[0]), dtype=bool)
    for polygon in polygons:
        local = tuple((x - spec.origin[0], y - spec.origin[1]) for x, y in polygon)
        canvas |= np.asarray(rasterize_polygon(spec.size, local)) > 0
    return canvas


# ---------------------------------------------------------------- the emitter

def test_the_fixture_is_the_shape_that_broke(plans):
    plan = plans[0]
    contours, _ = cv2.findContours(np.ascontiguousarray(plan.floor.astype(np.uint8)),
                                   cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    assert len(contours) == 1, "the rooms are one contour"
    assert 0.01 * cv2.arcLength(contours[0], True) > CORRIDOR, "wider than a corridor at 1%"
    assert plan.passed, plan.failed


def _pulled_back(spec, plan, by=60):
    """The same rooms with the floor stopped short of the door, as a gate may accept."""
    silhouette, chamber, editable = geometry_masks(spec)
    short = plan.floor & ~dilate_mask(door_mask(spec), by)
    return trace_plan_from_mask(short, spec, silhouette, chamber, editable)


@pytest.fixture(scope="module")
def spec(tmp_path_factory):
    return _spec(tmp_path_factory.mktemp("spec"))


@pytest.fixture(scope="module")
def plans(spec):
    """Built once: tracing a plan runs every check, which is most of this file's time."""
    rooms = _three_rooms(spec)
    return [rooms, _pulled_back(spec, rooms)]


def test_no_wall_lands_on_walkable_ground(spec, plans):
    """Not on the floor, not in the way in -- and no piece encloses a room, which a map
    polygon (no holes) would otherwise fill solid."""
    for plan in plans:
        walkable = erode(emit_mod.walkable_mask(plan), SLACK)
        walls = _raster(spec, emit_mod.wall_pieces(plan))
        shell = _raster(spec, emit_mod.shell_pieces(plan))

        assert walls.any() and shell.any()
        assert not (walls & walkable).any(), f"{int((walls & walkable).sum())} px walled"
        assert not (shell & walkable).any(), f"{int((shell & walkable).sum())} px shelled"


def test_the_walls_are_solid(spec, plans):
    """Every pixel of each strip is inside some piece: no threads, no wedges, no seams
    where a ring was cut."""
    for plan in plans:
        for strip, pieces in ((emit_mod.wall_mask(plan), emit_mod.wall_pieces(plan)),
                              (emit_mod.shell_mask(plan), emit_mod.shell_pieces(plan))):
            missed = erode(strip, SLACK) & ~_raster(spec, pieces)
            assert not missed.any(), f"{int(missed.sum())} px of wall missing"


def test_the_outer_wall_opens_only_at_the_door(spec, plans):
    """Its one gap is the door polygon -- not a disc round it, which with a floor that stops
    short opened the face either side of the frame."""
    silhouette = geometry_masks(spec)[0]
    face = silhouette & ~emit_mod._shrink(silhouette, 8) & emit_mod._shrink(silhouette, 2)
    # The way in is the door swept inward in whole-pixel steps, so its sides wobble a pixel.
    door = dilate_mask(door_mask(spec), SLACK)
    for plan in plans:
        open_ = face & ~_raster(spec, emit_mod.shell_pieces(plan))
        assert not (open_ & ~door).any(), f"{int((open_ & ~door).sum())} px open off the door"
        assert (open_ & door).any(), "and the door is open"


def test_the_way_in_is_open(plans):
    for plan in plans:
        assert emit_mod.problem(plan) == ""


def test_the_chamber_polygon_is_the_room_and_stays_off_the_door(spec, plans):
    """The roof hole and the trigger for "inside": within a pixel of the room, and never over
    the painted door, which is drawn over the player as a canopy."""
    plan = plans[0]
    drawn = _raster(spec, [emit_mod.chamber_from_plan(plan)])
    room = emit_mod.chamber_mask_from_plan(plan)

    assert not (drawn & ~dilate_mask(room, SLACK)).any(), "past the room"
    assert not (room & ~dilate_mask(drawn, SLACK)).any(), "short of the room"
    assert not (drawn & erode(door_mask(spec), SLACK)).any(), "over the door"


# ---------------------------------------------------------------- the gates

def _args(**overrides):
    values = dict(synthetic=False, draws=1, config=None, dry_run=False, redraw=False)
    values.update(overrides)
    return argparse.Namespace(**values)


def _scripted(monkeypatch, tmp_path, answers):
    """A gate with the viewer and the config out of the way, and these answers typed."""
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    monkeypatch.setattr(cli_mod, "_work", lambda building: work)
    monkeypatch.setattr(cli_mod, "_spec_path", lambda building: work / "interior.json")
    monkeypatch.setattr(cli_mod, "_show", lambda path: None)
    monkeypatch.setattr(cli_mod, "_config", lambda args: {})
    replies = iter(answers)
    monkeypatch.setattr(cli_mod, "_ask", lambda question, default="": next(replies))
    return work


def _draw(spec, work):
    return SimpleNamespace(spec=spec, passed=True, failed=[], report={"checks": []},
                           painted_path=work / "plan_draw1_raw.png",
                           composited_path=work / "plan_draw1_overlay.png", shape_path=None)


def _plan_gate_env(monkeypatch, draws, verdicts=("",)):
    monkeypatch.setattr(cli_mod, "_draw_or_reuse", draws)
    monkeypatch.setattr(plan_mod, "ranked_sheet", lambda plans, out: out)
    monkeypatch.setattr(plan_mod, "control_image", lambda plan: Image.new("RGB", (4, 4)))
    answers = iter(verdicts)
    monkeypatch.setattr(emit_mod, "problem", lambda plan: next(answers))


def test_a_draw_the_emitter_refuses_leaves_you_on_it_at_the_plan_gate(
        tmp_path, monkeypatch, capsys):
    spec = _spec(tmp_path)
    work = _scripted(monkeypatch, tmp_path, ["", ""])
    draw = _draw(spec, work)
    _plan_gate_env(monkeypatch, lambda *a, **k: [draw],
                   verdicts=["a quad closes the doorway", ""])

    assert cli_mod._plan_gate(spec, work, _args()) is draw
    assert "#1 cannot be emitted: a quad closes the doorway" in capsys.readouterr().err


def test_a_redraw_that_fails_keeps_the_draws_you_had(tmp_path, monkeypatch, capsys):
    spec = _spec(tmp_path)
    work = _scripted(monkeypatch, tmp_path, ["r", ""])
    draw = _draw(spec, work)
    calls = []

    def draws(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise ImageClientError("OpenAI API POST failed (500)")
        return [draw]

    _plan_gate_env(monkeypatch, draws)

    assert cli_mod._plan_gate(spec, work, _args()) is draw
    err = capsys.readouterr().err
    assert "drawing the plan failed -- ImageClientError" in err
    assert "with the draws you had" in err


def test_a_first_draw_that_fails_stops_cleanly(tmp_path, monkeypatch, capsys):
    spec = _spec(tmp_path)
    work = _scripted(monkeypatch, tmp_path, [])

    def draws(*args, **kwargs):
        raise ImageClientError("OpenAI API POST failed (500)")

    _plan_gate_env(monkeypatch, draws)

    assert cli_mod._plan_gate(spec, work, _args()) is None
    assert "drawing the plan failed" in capsys.readouterr().err


def _floor_gate_env(monkeypatch, spec, work, verdicts=("",), write_errors=()):
    traced = SimpleNamespace(spec=spec, report={"checks": [
        {"name": "floor_behind_door", "passed": True},
        {"name": "unpainted", "passed": True}]})
    monkeypatch.setattr(floor_mod, "draw_floor", lambda *a, **k: Image.new("RGB", (4, 4)))
    monkeypatch.setattr(floor_mod, "trace_floor", lambda painting, spec: traced)
    monkeypatch.setattr(floor_mod, "floor_overlay", lambda plan, source, out: out)
    monkeypatch.setattr(render_mod, "accept", lambda plan, composited: work / "interior.png")
    answers = iter(verdicts)
    monkeypatch.setattr(emit_mod, "problem", lambda plan: next(answers))
    errors = iter(write_errors)
    writes = []

    def write(plan, written):
        error = next(errors, None)
        if error:
            raise error
        writes.append(plan)

    monkeypatch.setattr(cli_mod, "_write_into_map", write)
    return traced, writes


def test_a_floor_the_emitter_refuses_leaves_you_at_the_floor_gate(
        tmp_path, monkeypatch, capsys):
    spec = _spec(tmp_path)
    work = _scripted(monkeypatch, tmp_path, ["", ""])
    traced, writes = _floor_gate_env(monkeypatch, spec, work,
                                     verdicts=["a quad closes the doorway", ""])

    kept = work / "render_composited.png"
    assert cli_mod._floor_gate(SimpleNamespace(spec=spec), kept, work, _args()) is traced
    assert len(writes) == 1, "written once, on the second [enter]"
    assert "not written: a quad closes the doorway" in capsys.readouterr().err


def test_a_write_a_held_file_stops_leaves_you_at_the_floor_gate(
        tmp_path, monkeypatch, capsys):
    spec = _spec(tmp_path)
    work = _scripted(monkeypatch, tmp_path, ["", ""])
    traced, writes = _floor_gate_env(monkeypatch, spec, work, verdicts=["", ""],
                                     write_errors=[PermissionError("map.tmx is in use")])

    kept = work / "render_composited.png"
    assert cli_mod._floor_gate(SimpleNamespace(spec=spec), kept, work, _args()) is traced
    assert len(writes) == 1
    assert "writing the map failed -- PermissionError" in capsys.readouterr().err


def test_a_floor_painting_that_cannot_be_drawn_goes_back_to_the_render(
        tmp_path, monkeypatch, capsys):
    spec = _spec(tmp_path)
    work = _scripted(monkeypatch, tmp_path, [])
    _floor_gate_env(monkeypatch, spec, work)

    def fails(*args, **kwargs):
        raise ImageClientError("moderation blocked")

    monkeypatch.setattr(floor_mod, "draw_floor", fails)

    kept = work / "render_composited.png"
    assert cli_mod._floor_gate(SimpleNamespace(spec=spec), kept, work, _args()) == "back"
    assert "back to the render gate" in capsys.readouterr().err


def test_back_from_the_floor_gate_chooses_a_render_again_without_buying_one(
        tmp_path, monkeypatch):
    spec = _spec(tmp_path)
    work = _scripted(monkeypatch, tmp_path, [])
    entered = []

    def render_gate(plan, work, args):
        entered.append(args.redraw)
        return work / "render_composited.png"

    outcomes = iter(["back", True])
    monkeypatch.setattr(cli_mod, "_render_gate", render_gate)
    monkeypatch.setattr(cli_mod, "_accept_and_write", lambda *args: next(outcomes))

    assert cli_mod._render_then_accept(SimpleNamespace(spec=spec), work,
                                       _args(redraw=True)) is True
    assert entered == [True, False], "--redraw buys one render, not one per trip back"


# ---------------------------------------------------------------- a new choice clears what follows

def _touch(work, *names):
    for name in names:
        (work / name).write_bytes(b"x")


def _set_aside(work):
    return sorted(p.name for p in (work / "old").rglob("*") if p.is_file())


def test_keeping_a_different_plan_sets_aside_what_was_made_from_the_old_one(
        spec, tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(work / "plan_control.png")
    _touch(work, "render_composited.png", "render_raw.png", "control.png",
           "augment_meta.json", "floor_raw.png", "floor_meta.json", "plan_draw1_raw.png")
    monkeypatch.setattr(plan_mod, "control_image",
                        lambda plan: Image.new("RGB", (4, 4), (0, 0, 255)))

    cli_mod._keep_plan(_draw(spec, work), work)

    assert _set_aside(work) == ["augment_meta.json", "control.png", "floor_meta.json",
                                "floor_raw.png", "render_composited.png", "render_raw.png"]
    assert (work / "plan_draw1_raw.png").exists(), "the plan step's own draws stay"
    assert (work / "plan.pickle").exists()
    with Image.open(work / "plan_control.png") as kept:
        assert kept.convert("RGB").getpixel((0, 0)) == (0, 0, 255)


def test_keeping_the_same_plan_keeps_what_was_made_from_it(spec, tmp_path, monkeypatch):
    """Back to the plan gate and forward again without changing it costs nothing."""
    work = tmp_path / "work"
    work.mkdir()
    Image.new("RGB", (4, 4), (0, 0, 255)).save(work / "plan_control.png")
    _touch(work, "render_composited.png", "floor_raw.png")
    monkeypatch.setattr(plan_mod, "control_image",
                        lambda plan: Image.new("RGB", (4, 4), (0, 0, 255)))

    cli_mod._keep_plan(_draw(spec, work), work)

    assert (work / "render_composited.png").exists() and (work / "floor_raw.png").exists()
    assert not (work / "old").exists()


def test_a_new_render_sets_aside_the_floor_trace(spec, tmp_path, monkeypatch):
    work = _scripted(monkeypatch, tmp_path, ["r", ""])
    _touch(work, "render_composited.png", "floor_raw.png", "floor_meta.json")
    monkeypatch.setattr(render_mod, "render_interior",
                        lambda *a, **k: [work / "render_composited.png"])

    kept = cli_mod._render_gate(SimpleNamespace(spec=spec), work, _args())

    assert kept == work / "render_composited.png"
    assert _set_aside(work) == ["floor_meta.json", "floor_raw.png"]


def test_a_plan_that_cannot_be_kept_leaves_you_at_the_plan_gate(
        spec, tmp_path, monkeypatch, capsys):
    work = _scripted(monkeypatch, tmp_path, ["", ""])
    draw = _draw(spec, work)
    _plan_gate_env(monkeypatch, lambda *a, **k: [draw], verdicts=["", ""])
    attempts = []

    def keep(plan, work):
        attempts.append(plan)
        if len(attempts) == 1:
            raise PermissionError("could not move render_composited.png aside")

    monkeypatch.setattr(cli_mod, "_keep_plan", keep)

    assert cli_mod._plan_gate(spec, work, _args()) is draw
    assert len(attempts) == 2, "kept on the second [enter]"
    assert "keeping the plan failed" in capsys.readouterr().err


# ---------------------------------------------------------------- the door's frame

MINIMAL_MAP = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" orientation="orthogonal" renderorder="right-down" width="10" height="10" tilewidth="150" tileheight="150" infinite="0" nextlayerid="3" nextobjectid="1">
 <objectgroup id="1" name="ObstaclePolygons">
 </objectgroup>
 <objectgroup id="2" name="Buildings">
 </objectgroup>
</map>
"""


def test_the_door_frame_leaves_the_doorway_and_the_way_up_to_it_clear(spec):
    """The frame is what the game draws over a body under it: never the opening he stands
    in, never the ground he walks up on."""
    frame = emit_mod.door_frame_mask(spec)
    opening = door_mask(spec)
    silhouette = geometry_masks(spec)[0]
    outward = (-spec.door_inward[0], -spec.door_inward[1])
    in_front = emit_mod._dragged(opening, outward, emit_mod.DOOR_FRAME_PX) & ~opening

    assert frame.any(), "there is a lintel and jambs"
    assert not (frame & opening).any(), "a body in the doorway is not covered"
    assert not (frame & ~silhouette).any()
    assert not (frame & in_front).any(), "nor one walking up to it"


def test_accepting_twice_rewrites_the_door_rather_than_stacking_it(plans, tmp_path):
    target = tmp_path / "map.tmx"
    target.write_text(MINIMAL_MAP, encoding="utf-8")
    for _ in range(2):
        emit_mod.write_plan(plans[0], target)

    root = ET.parse(target).getroot()
    doors = [o for o in root.iter("object")
             if (o.get("name") or "").startswith("test_pyramid_door")]
    assert doors
    assert len(doors) == len({o.get("name") for o in doors}), "replaced, not stacked"
    for door in doors:
        props = {p.get("name"): p.get("value") for p in door.findall("properties/property")}
        assert props.get("door_of") == "test_pyramid"
    assert len([o for o in root.iter("object") if o.get("name") == "test_pyramid"]) == 1
