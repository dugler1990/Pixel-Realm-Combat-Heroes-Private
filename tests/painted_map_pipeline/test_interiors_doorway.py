"""The door polygon and the room behind it: the emitter, the floor tracer, the reload.

One door polygon (`door_of`) is read by four things -- the plan's hold-out, the render's
restore, the emitter's chamber and doorway zone, and the engine's overhead area -- and
these pin the three facts that keep them one thing: the room never covers the door, the
walk from the door to the floor is never walled, and a door drawn on the map after the
plan was kept is seen by every command that reloads the plan.
"""

from __future__ import annotations

import dataclasses
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.painted_map_pipeline.interiors import cli as cli_mod
from tools.painted_map_pipeline.interiors import emit as emit_mod
from tools.painted_map_pipeline.interiors import floor as floor_mod
from tools.painted_map_pipeline.interiors import plan as plan_mod
from tools.painted_map_pipeline.interiors import spec as spec_mod
from tools.painted_map_pipeline.interiors.checks import erode
from tools.painted_map_pipeline.interiors.plan import door_mask, geometry_masks, trace_plan_from_mask
from tools.painted_map_pipeline.interiors.render import restore_doorway
from tools.painted_map_pipeline.interiors.trace import FLOOR_RGB, OUTER_RGB, SOLID_RGB
from tools.painted_map_pipeline.world_levels.geometry import dilate_mask
from tools.painted_map_pipeline.world_levels.masks import rasterize_polygon

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


def _map_copy(tmp_path):
    target = tmp_path / "map.tmx"
    shutil.copyfile(MAP, target)
    return target


def _names(map_path):
    root = ET.parse(map_path).getroot()
    return [o.get("name") for group in root.iter("objectgroup")
            for o in group.findall("object") if o.get("name")]


def _raster(spec, world_polygon):
    local = tuple((x - spec.origin[0], y - spec.origin[1]) for x, y in world_polygon)
    return np.asarray(rasterize_polygon(spec.size, local)) > 0


def _door_line(spec, floor):
    """Steps along the door line from the door point to the first floor pixel."""
    ox, oy = spec.door_origin
    ix, iy = spec.door_inward
    h, w = floor.shape
    for step in range(int(10 * spec.tile)):
        x, y = int(round(ox + ix * step)), int(round(oy + iy * step))
        if not (0 <= x < w and 0 <= y < h) or floor[y, x]:
            return
        yield x, y


def _blocked(spec, shape, quads):
    blocked = np.zeros(shape, dtype=bool)
    for quad in quads:
        blocked |= _raster(spec, quad)
    return blocked


# ---------------------------------------------------------------- the room and the door

def test_the_chamber_starts_behind_the_door(plan, spec):
    """The room polygon never covers the painted door: in play the door is a canopy over
    the player, and a hole there would show the model's doorway under the map's. Rasterised,
    with a pixel of give for the outline -- not a vertex test."""
    assert spec.doors, "the fixture building has an authored door_of polygon"
    polygon = emit_mod.chamber_from_plan(plan)
    chamber = _raster(spec, polygon)
    door = erode(door_mask(spec), 2)

    assert door.any()
    assert not (chamber & door).any()


def test_the_passage_is_open(plan, spec, tmp_path):
    """No wall on the walk from the door point to the floor -- the line the gate walked --
    and `write_plan` would have refused otherwise."""
    quads = emit_mod.wall_pieces(plan) + emit_mod.shell_pieces(plan)
    blocked = _blocked(spec, plan.floor.shape, quads)
    steps = list(_door_line(spec, plan.floor))

    assert steps, "the walk reaches floor"
    assert not any(blocked[y, x] for x, y in steps)
    emit_mod.assert_passage_open(plan, quads)          # the same fact, as the emitter checks it
    emit_mod.write_plan(plan, _map_copy(tmp_path))      # and it does not raise


def test_a_closed_doorway_is_refused(plan, spec):
    """A quad laid straight across the door line is caught before the map is touched."""
    ox, oy = spec.door_origin
    ix, iy = spec.door_inward
    tx, ty = -iy, ix
    depth = 40                                         # inside the frame, before the floor
    centre = (spec.origin[0] + ox + ix * depth, spec.origin[1] + oy + iy * depth)
    bar = [(centre[0] + tx * 300 + ix * s, centre[1] + ty * 300 + iy * s) for s in (-10, 10)]
    bar += [(centre[0] - tx * 300 + ix * s, centre[1] - ty * 300 + iy * s) for s in (10, -10)]
    with pytest.raises(ValueError, match="closes the doorway"):
        emit_mod.assert_passage_open(plan, [bar])


def test_a_floor_that_stops_short_is_not_walled(plan, spec):
    """The gate accepts a floor up to three player-widths behind the door. Whatever gap it
    accepted, the emitter must not wall: the way in is the door swept on to the floor."""
    silhouette, chamber, editable = geometry_masks(spec)
    short = plan.floor & ~dilate_mask(door_mask(spec), 60)
    pulled = trace_plan_from_mask(short, spec, silhouette, chamber, editable)
    gap = next(c for c in pulled.report["checks"] if c["name"] == "floor_behind_door")
    # Measured along the door line, which crosses the (axis-aligned) door rect at a slant,
    # so it comes out longer than the 60 px erosion; what matters is that the gate passed it.
    assert gap["passed"] and gap["gap_px"] > 0, gap

    quads = emit_mod.wall_pieces(pulled)
    blocked = _blocked(spec, short.shape, quads)
    assert not any(blocked[y, x] for x, y in _door_line(spec, short))
    emit_mod.assert_passage_open(pulled, quads)
    assert blocked.any(), "the rest of the room is still walled"


def test_the_gate_measures_the_gap_in_px(plan):
    gap = next(c for c in plan.report["checks"] if c["name"] == "floor_behind_door")
    assert gap["gap_px"] == 0, "the synthetic floor reaches the door"


def test_no_hole_object_is_written(plan, tmp_path):
    target = _map_copy(tmp_path)
    emit_mod.write_plan(plan, target)
    assert not [n for n in _names(target) if n.startswith(f"{BUILDING}_hole")]


def test_the_door_is_rewritten_as_its_frame(plan, tmp_path):
    """The map's door is generated now -- the frame round the opening -- and replaced on
    every write, not stacked."""
    target = _map_copy(tmp_path)
    emit_mod.write_plan(plan, target)
    emit_mod.write_plan(plan, target)
    doors = [o for o in ET.parse(target).getroot().iter("object")
             if (o.get("name") or "").startswith("great_pyramid_door")]
    assert doors and len(doors) == len({o.get("name") for o in doors})


def test_rooms_go_to_the_spawner_layer_never_buildings(plan, tmp_path):
    target = _map_copy(tmp_path)
    root = ET.parse(target).getroot()
    assert root.find("objectgroup[@name='spawner']") is None, "the fixture map has no spawner layer"
    layer_id_before = int(root.get("nextlayerid"))

    result = emit_mod.write_plan(plan, target)
    root = ET.parse(target).getroot()
    spawner = root.find("objectgroup[@name='spawner']")
    buildings = root.find("objectgroup[@name='Buildings']")

    assert spawner is not None, "created when the map has none"
    assert int(root.get("nextlayerid")) == layer_id_before + 1
    rooms = [o.get("name") for o in spawner.findall("object")]
    assert len(rooms) == result["rooms"] > 0
    assert all(n.startswith(f"{BUILDING}_room") for n in rooms)
    assert not [o.get("name") for o in buildings.findall("object")
                if (o.get("name") or "").startswith(f"{BUILDING}_room")]
    # Idempotent: a second write reuses the layer and replaces the rooms.
    emit_mod.write_plan(plan, target)
    root = ET.parse(target).getroot()
    assert len(root.findall("objectgroup[@name='spawner']")) == 1
    assert len(root.find("objectgroup[@name='spawner']").findall("object")) == result["rooms"]


def test_restore_doorway_writes_the_roof_back_over_the_door(spec):
    roof = Image.new("RGBA", tuple(spec.size), (10, 20, 30, 255))
    candidate = Image.new("RGBA", tuple(spec.size), (200, 200, 200, 255))
    out = np.asarray(restore_doorway(candidate, roof, spec))
    door = door_mask(spec)
    assert door.any()
    assert (out[door][:, :3] == (10, 20, 30)).all(), "the door is the roof's"
    assert (out[~door][:, :3] == (200, 200, 200)).all(), "nothing else changed"


# ---------------------------------------------------------------- the floor pass

def test_the_floor_tracer_keeps_walkable_inside_the_room_and_walls_out_of_the_door(spec):
    """A three-colour painting: magenta inside the requested room and spilling over the door
    and the shell, green walls around it, blue beyond. Floor is clipped to where floor was
    allowed; walls stay; the chamber is floor and walls, never the door."""
    silhouette, chamber, editable = geometry_masks(spec)
    room = erode(editable, 200)                      # a floor well inside the request
    spill = dilate_mask(room, 260) & silhouette      # ...spilling past editable and into the door
    walls = dilate_mask(room, 120) & ~room & silhouette
    canvas = np.zeros((spec.size[1], spec.size[0], 3), dtype=np.uint8)
    canvas[silhouette] = OUTER_RGB
    canvas[spill] = FLOOR_RGB
    canvas[walls] = SOLID_RGB
    canvas[room] = FLOOR_RGB
    assert (spill & ~editable).any(), "the painting spills somewhere floor is not allowed"

    traced = floor_mod.trace_floor(Image.fromarray(canvas, mode="RGB"), spec)

    assert not (traced.floor & ~editable).any(), "spilled floor is dropped"
    assert (traced.floor & room).sum() > 0.95 * room.sum()
    assert traced.classes["wall"].any()
    assert not (traced.classes["wall"] & traced.floor).any()
    chamber_mask = emit_mod.chamber_mask_from_plan(traced)
    assert not (chamber_mask & door_mask(spec)).any(), "the door is never in the room"
    assert (chamber_mask & traced.classes["wall"]).any(), "the painted walls are in the room"
    assert not (chamber_mask & traced.classes["outer"]).any(), "the outside face never is"


def test_the_floor_tracer_resizes_a_hand_painting(spec):
    small = Image.new("RGB", (spec.size[0] // 4, spec.size[1] // 4), OUTER_RGB)
    traced = floor_mod.trace_floor(small, spec)
    assert traced.floor.shape == (spec.size[1], spec.size[0])
    assert not traced.floor.any()


# ---------------------------------------------------------------- reloading a kept plan

def test_the_maps_door_is_not_read_back_as_the_opening(spec, tmp_path, monkeypatch):
    """The map's door is the frame the emitter wrote. Reading it back as the opening would
    hold the floor out of the frame instead of the doorway on the next run."""
    target = _map_copy(tmp_path)
    saved = dataclasses.replace(spec, map_path=str(target))
    work = tmp_path / "work" / saved.building
    work.mkdir(parents=True)
    monkeypatch.setattr(cli_mod, "_spec_path", lambda building: work / "interior.json")
    saved.save(work / "interior.json")

    loaded = cli_mod._load_spec(saved.building)

    assert loaded.doors == saved.doors
