"""The door polygon and the room behind it.

One door polygon (`door_of`) is read by four things -- the plan's hold-out, the render's
restore, the emitter's chamber and doorway zone, and the engine's overhead area -- and
these pin the facts that keep them one thing: the room never covers the door, and the
walk from the door to the floor is never walled.
"""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.painted_map_pipeline.interiors import emit as emit_mod
from tools.painted_map_pipeline.interiors import plan as plan_mod
from tools.painted_map_pipeline.interiors import spec as spec_mod
from tools.painted_map_pipeline.interiors.checks import erode
from tools.painted_map_pipeline.interiors.plan import door_mask
from tools.painted_map_pipeline.interiors.render import restore_doorway
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


def test_a_closed_doorway_is_refused(plan, spec):
    """A quad laid straight across the door line is caught before the map is touched. With
    the shell, as the map gets it: alone, the quad is a post a body walks round."""
    ox, oy = spec.door_origin
    ix, iy = spec.door_inward
    tx, ty = -iy, ix
    depth = 40                                         # inside the frame, before the floor
    centre = (spec.origin[0] + ox + ix * depth, spec.origin[1] + oy + iy * depth)
    bar = [(centre[0] + tx * 300 + ix * s, centre[1] + ty * 300 + iy * s) for s in (-10, 10)]
    bar += [(centre[0] - tx * 300 + ix * s, centre[1] - ty * 300 + iy * s) for s in (10, -10)]
    with pytest.raises(ValueError, match="closes the doorway"):
        emit_mod.assert_passage_open(plan, [bar] + emit_mod.shell_pieces(plan))


def test_the_gate_measures_the_gap_in_px(plan):
    gap = next(c for c in plan.report["checks"] if c["name"] == "floor_behind_door")
    assert gap["gap_px"] == 0, "the synthetic floor reaches the door"


def test_restore_doorway_writes_the_roof_back_over_the_door(spec):
    roof = Image.new("RGBA", tuple(spec.size), (10, 20, 30, 255))
    candidate = Image.new("RGBA", tuple(spec.size), (200, 200, 200, 255))
    out = np.asarray(restore_doorway(candidate, roof, spec))
    door = door_mask(spec)
    assert door.any()
    assert (out[door][:, :3] == (10, 20, 30)).all(), "the door is the roof's"
    assert (out[~door][:, :3] == (200, 200, 200)).all(), "nothing else changed"
