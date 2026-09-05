"""The border gate, and the canvas arithmetic that keeps every pass a legal edit call.

The point of these is that a building interior which does not register with its exterior
can never reach the game: `check_border` is byte equality, so a drifting draw fails on the
pass that produced it rather than turning into renderer workarounds later.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.painted_map_pipeline.building_interiors import (
    BuildingInteriorError,
    build_masks,
    check_border,
    cut_alpha,
    layout_size,
    load_building,
    paste_back,
    tile_rows,
)
from tools.painted_map_pipeline.openai_api import validate_size

MAP = Path("levels/Frostreach/sunspine_7x6_play/map.tmx")
needs_level = pytest.mark.skipif(not MAP.exists(), reason="Frostreach level assets not present")

CANVAS = (3600, 3140)


def _canvas(colour):
    return Image.new("RGBA", (40, 30), colour)


def _chamber_mask():
    mask = np.zeros((30, 40), dtype=bool)
    mask[10:20, 10:30] = True
    return mask


# ------------------------------------------------------------------ canvas arithmetic

def test_layout_size_is_the_largest_legal_uniform_fit():
    width, height = layout_size(CANVAS)
    assert (width, height) == (3072, 2688)
    validate_size(width, height)  # raises if the API would reject it
    assert width / height == pytest.approx(CANVAS[0] / CANVAS[1], abs=0.01)


def test_full_canvas_would_be_rejected():
    """The reason there is a layout pass at all: 11.3 MP against an 8.3 MP cap."""
    with pytest.raises(Exception):
        validate_size(*CANVAS)


def test_tile_rows_are_legal_canvases_that_overlap_and_cover_the_chamber():
    rows = tile_rows(CANVAS[1])
    assert rows == [(0, 1600), (1536, 3136)]
    for top, bottom in rows:
        validate_size(CANVAS[0], bottom - top)
    assert rows[1][0] < rows[0][1], "bands must overlap or the seam has no shared context"


# ------------------------------------------------------------------ the gate

def test_paste_back_keeps_the_border_exact_whatever_the_model_returns():
    roof = _canvas((10, 20, 30, 255))
    rng = np.random.default_rng(0)
    noise = Image.fromarray(rng.integers(0, 255, (30, 40, 4), dtype=np.uint8), mode="RGBA")
    chamber = _chamber_mask()

    merged = paste_back(noise, roof, chamber)

    check_border(merged, roof, ~chamber)
    assert (np.asarray(merged)[chamber] == np.asarray(noise)[chamber]).all()


def test_check_border_rejects_a_single_drifted_pixel():
    roof = _canvas((10, 20, 30, 255))
    drifted = np.asarray(roof).copy()
    drifted[0, 0] = (11, 20, 30, 255)

    with pytest.raises(BuildingInteriorError, match="border check failed"):
        check_border(Image.fromarray(drifted, mode="RGBA"), roof, ~_chamber_mask())


def test_cut_alpha_clears_outside_the_silhouette_only():
    footprint = np.zeros((30, 40), dtype=bool)
    footprint[5:25, 5:35] = True

    out = np.asarray(cut_alpha(_canvas((1, 2, 3, 255)), footprint))

    assert (out[..., 3][footprint] == 255).all()
    assert (out[..., 3][~footprint] == 0).all()


# ------------------------------------------------------------------ against the real map

@needs_level
def test_load_building_reads_the_footprint_and_its_chamber():
    art = load_building(MAP, "great_pyramid")

    assert art.origin == (5850, 2690)
    assert art.size == CANVAS
    assert art.roof_path.name == "great_pyramid_roof.png"

    footprint, chamber = build_masks(art)
    assert not (chamber & ~footprint).any(), "chamber must sit inside the footprint"
    # The chamber is the silhouette inset by one wall thickness, so it is most of the
    # canvas: an interior that only filled a small room would leave the rest unpainted.
    assert 0.3 < chamber.mean() < 0.5


@needs_level
def test_the_painted_door_is_held_out_of_the_editable_region():
    """The first real run repainted the pyramid's lintel into plain masonry.

    The door stands on the wall, so the chamber boundary runs straight through it: 39% of
    its bounding box was editable and the model reinvented that half as solid stone,
    leaving the kept threshold opening into a wall. Held out, it survives in both views.
    """
    art = load_building(MAP, "great_pyramid")
    assert art.doors, "great_pyramid_door (door_of=great_pyramid) is missing from the map"

    _footprint, editable = build_masks(art)

    door = np.zeros_like(editable)
    xs = [int(p[0]) for p in art.doors[0]]
    ys = [int(p[1]) for p in art.doors[0]]
    door[min(ys):max(ys), min(xs):max(xs)] = True
    assert not (editable & door).any(), "no part of the painted door may be repainted"
    assert editable.mean() > 0.3, "holding the door out must not gut the editable region"


@needs_level
def test_missing_chamber_is_an_error_not_a_silent_full_canvas_repaint():
    with pytest.raises(BuildingInteriorError, match="no object named"):
        load_building(MAP, "not_a_building")


@needs_level
def test_shipped_interior_registers_with_its_roof():
    art = load_building(MAP, "great_pyramid")
    footprint, chamber = build_masks(art)
    roof = Image.open(art.roof_path).convert("RGBA")
    interior = Image.open(art.interior_path).convert("RGBA")

    check_border(interior, roof, footprint & ~chamber)
