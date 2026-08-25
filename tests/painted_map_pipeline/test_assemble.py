"""Stitching accepted levels back into one world image, and registering the result."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image

from tools.painted_map_pipeline.world_levels.assemble import assemble_world, core_coverage
from tools.painted_map_pipeline.world_levels.config import load_config
from tools.painted_map_pipeline.world_levels.package_builder import level_paths, prepare_run
from tools.painted_map_pipeline.world_levels.state_store import atomic_write_json, read_json

CSV_FIELDS = [
    "id", "name", "region", "crop_x_px", "crop_y_px", "crop_width_px", "crop_height_px",
    "overlap_buffer_px", "core_polygon_points_px", "generation_polygon_points_px",
    "connections",
]


def _run(tmp_path: Path) -> Path:
    """A two-level run over a 40x20 world, cores meeting exactly at x=20."""
    world_path = tmp_path / "world.png"
    world = np.zeros((20, 40, 4), dtype=np.uint8)
    world[..., :3] = 60                       # a flat grey source, easy to tell art from
    world[..., 3] = 255
    Image.fromarray(world, "RGBA").save(world_path)

    plan_path = tmp_path / "levels.csv"
    with plan_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows([
            {"id": "01", "name": "West", "region": "T", "crop_x_px": 0, "crop_y_px": 0,
             "crop_width_px": 24, "crop_height_px": 20, "overlap_buffer_px": 4,
             "core_polygon_points_px": "0:0|19:0|19:19|0:19",
             "generation_polygon_points_px": "0:0|23:0|23:19|0:19", "connections": "02"},
            {"id": "02", "name": "East", "region": "T", "crop_x_px": 16, "crop_y_px": 0,
             "crop_width_px": 24, "crop_height_px": 20, "overlap_buffer_px": 4,
             "core_polygon_points_px": "20:0|39:0|39:19|20:19",
             "generation_polygon_points_px": "16:0|39:0|39:19|16:19", "connections": "01"},
        ])

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "world_map": str(world_path),
        "level_plan": str(plan_path),
        "output_root": str(tmp_path / "out"),
        "canvas": {"mode": "explicit", "width": 24, "height": 20,
                   "placement": "center", "margin": 0},
        "scale": {"pixels_per_world_pixel": 1},
        "rendering": {"outside_color": [0, 0, 0, 255], "source_resampling": "nearest"},
        "execution": {"approval_mode": "manual", "stop_on_failure": True, "retry_limit": 0},
        "generation": {"provider": "copy"},
        "style_prompt": "T",
    }), encoding="utf-8")
    prepare_run(load_config(config_path))
    return tmp_path / "out"


def _accept(root: Path, level_id: str, colour: tuple[int, int, int], index: int) -> None:
    """Stand in for a finished generation: a flat colour accepted for this level."""
    paths = level_paths(root, level_id)
    manifest = read_json(paths["manifest"])
    art = Image.new("RGB", tuple(manifest["canvas_size"]), colour)
    accepted = paths["root"] / "accepted" / "image.png"
    accepted.parent.mkdir(parents=True, exist_ok=True)
    art.save(accepted)
    manifest.update({"state": "accepted", "accepted_image": str(accepted),
                     "acceptance_index": index})
    atomic_write_json(paths["manifest"], manifest)
    run = read_json(root / "run.json")
    run["levels"][level_id]["state"] = "accepted"
    atomic_write_json(root / "run.json", run)


def test_accepted_art_lands_at_its_world_position(tmp_path: Path):
    """Placement has to be exact, not close: a few pixels out and every join is wrong."""
    root = _run(tmp_path)
    _accept(root, "01", (200, 40, 40), 1)
    _accept(root, "02", (40, 40, 200), 2)

    world, info = assemble_world(root)
    assert info["levels_placed"] == 2
    pixels = np.asarray(world.convert("RGB"))
    # the cores meet at x=20, so each half is one level's colour and nothing bleeds across
    assert (pixels[:, :20] == (200, 40, 40)).all()
    assert (pixels[:, 20:] == (40, 40, 200)).all()


def test_ungenerated_ground_falls_back_to_the_source_or_black(tmp_path: Path):
    """A run is judged half finished; the map has to stay walkable while it is."""
    root = _run(tmp_path)
    _accept(root, "01", (200, 40, 40), 1)

    filled, info = assemble_world(root)
    assert info["levels_placed"] == 1 and info["missing"] == ["02"]
    pixels = np.asarray(filled.convert("RGB"))
    assert (pixels[:, :20] == (200, 40, 40)).all()
    assert (pixels[:, 20:] == 60).all()          # the source map, not a hole

    dark, _ = assemble_world(root, fallback=False)
    assert (np.asarray(dark.convert("RGB"))[:, 20:] == 0).all()


def test_cores_tile_without_overlapping(tmp_path: Path):
    """The whole stitch rests on cores not overlapping, so it is worth being able to check."""
    root = _run(tmp_path)
    _accept(root, "01", (200, 40, 40), 1)
    _accept(root, "02", (40, 40, 200), 2)

    coverage = core_coverage(root)
    assert coverage["overlapping_px"] == 0
    assert coverage["covered_px"] == coverage["world_px"]


def test_register_is_idempotent_and_keeps_every_existing_level(tmp_path: Path):
    """It edits real game code, so adding a level must not disturb the ones already there."""
    from tools.painted_map_pipeline.world_levels.register_level import (
        existing_levels, register, taken_slots,
    )

    repo = Path(__file__).resolve().parents[2]
    before_levels, before_slots = existing_levels(repo), taken_slots(repo)
    assert 11 in before_levels and (1, 0) in before_slots

    # already registered by a real run: re-registering must be a no-op
    again = register(repo, slug="sunspine_7x6_play", number=12, slot=(1, 2))
    assert again["changed"] == []
    assert not again["ternary_refactored"]
    assert existing_levels(repo) == before_levels
    assert taken_slots(repo) == before_slots
