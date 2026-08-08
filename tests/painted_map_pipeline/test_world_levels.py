from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.painted_map_pipeline.world_levels.batch_runner import parse_level_selector, run_batch
from tools.painted_map_pipeline.world_levels.config import load_config
from tools.painted_map_pipeline.world_levels.coordinates import ScaledSpace, build_transform
from tools.painted_map_pipeline.world_levels.job_builder import canvas_asset, create_job
from tools.painted_map_pipeline.world_levels.masks import compute_overlap
from tools.painted_map_pipeline.world_levels.package_builder import level_paths, prepare_run
from tools.painted_map_pipeline.world_levels.package_refresher import refresh_level
from tools.painted_map_pipeline.world_levels.plan_loader import load_level_plan
from tools.painted_map_pipeline.world_levels.result_ingest import ingest_result
from tools.painted_map_pipeline.world_levels.state_store import read_json, sha256_file
from tools.painted_map_pipeline.world_levels.validate_continuity import validate_run


CSV_FIELDS = [
    "id",
    "name",
    "region",
    "crop_x_px",
    "crop_y_px",
    "crop_width_px",
    "crop_height_px",
    "overlap_buffer_px",
    "core_polygon_points_px",
    "generation_polygon_points_px",
    "connections",
]


def _write_fixture(
    tmp_path: Path,
    *,
    canvas: dict | None = None,
    generation: dict | None = None,
    name: str = "",
) -> Path:
    """Write a world image, level plan and config into ``tmp_path``.

    ``name`` gives the run its own output root and config file, so two runs can be prepared
    side by side from the same world and plan -- which is how the renderers get compared.
    """
    world_path = tmp_path / "world.png"
    world = np.zeros((10, 20, 4), dtype=np.uint8)
    for y in range(10):
        for x in range(20):
            world[y, x] = (x * 10, y * 20, 100, 255)
    Image.fromarray(world, mode="RGBA").save(world_path)

    plan_path = tmp_path / "levels.csv"
    rows = [
        {
            "id": "01",
            "name": "West",
            "region": "Test",
            "crop_x_px": 0,
            "crop_y_px": 0,
            "crop_width_px": 12,
            "crop_height_px": 10,
            "overlap_buffer_px": 2,
            "core_polygon_points_px": "1:1|8:1|8:8|1:8",
            "generation_polygon_points_px": "0:0|10:0|10:9|0:9",
            "connections": "02",
        },
        {
            "id": "02",
            "name": "East",
            "region": "Test",
            "crop_x_px": 8,
            "crop_y_px": 0,
            "crop_width_px": 12,
            "crop_height_px": 10,
            "overlap_buffer_px": 2,
            "core_polygon_points_px": "10:1|18:1|18:8|10:8",
            "generation_polygon_points_px": "8:0|19:0|19:9|8:9",
            "connections": "01",
        },
    ]
    with plan_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    config_path = tmp_path / f"config{name}.json"
    config_path.write_text(
        json.dumps(
            {
                "world_map": str(world_path),
                "level_plan": str(plan_path),
                "output_root": str(tmp_path / f"output{name}"),
                "canvas": canvas
                or {
                    "mode": "derived",
                    "placement": "center",
                    "margin": 1,
                },
                "scale": {"pixels_per_world_pixel": 2},
                "rendering": {
                    "outside_color": [0, 0, 0, 255],
                    "source_resampling": "nearest",
                },
                "execution": {
                    "approval_mode": "manual",
                    "stop_on_failure": True,
                    "retry_limit": 0,
                },
                "generation": generation or {"provider": "copy"},
                "style_prompt": "Test prompt.",
            }
        ),
        encoding="utf-8",
    )
    return config_path


def test_prepare_uses_configured_canvas_and_binary_masks(tmp_path: Path):
    config = load_config(_write_fixture(tmp_path))
    run = prepare_run(config)
    assert run["canvas_size"] == [26, 22]
    paths = level_paths(config.output_root, "01")
    with Image.open(paths["generation_mask"]) as mask:
        assert set(np.unique(np.asarray(mask))).issubset({0, 255})
    # The prepared template is dense: masking to the polygon is a renderer's presentation
    # choice, so the world map survives outside it rather than being cut away here.
    with Image.open(paths["dense_template"]) as dense, Image.open(paths["generation_mask"]) as mask:
        outside = np.asarray(dense)[np.asarray(mask) == 0]
        assert np.any(outside != np.array([0, 0, 0, 255]))


def test_explicit_canvas_rejects_scaled_crop_that_does_not_fit(tmp_path: Path):
    config_path = _write_fixture(
        tmp_path,
        canvas={"mode": "explicit", "width": 20, "height": 20, "placement": "center", "margin": 0},
    )
    with pytest.raises(ValueError, match="cannot fit"):
        prepare_run(load_config(config_path))


def test_acceptance_embeds_exact_neighbor_pixels_and_restores_locks(tmp_path: Path):
    config = load_config(_write_fixture(tmp_path))
    prepare_run(config)
    root = config.output_root
    refresh_level(root, "01")
    first_job = create_job(root, "01")
    ingest_result(root, "01", first_job.input_path, attempt=first_job.attempt, auto_accept=True)

    second_paths = level_paths(root, "02")
    manifest = read_json(second_paths["manifest"])
    assert [entry["neighbor_id"] for entry in manifest["locked_sources"]] == ["01"]
    revision = manifest["context_revision"]
    input_hash = sha256_file(second_paths["generation_input"])
    refresh_level(root, "02")
    refreshed = read_json(second_paths["manifest"])
    assert refreshed["context_revision"] == revision
    assert sha256_file(second_paths["generation_input"]) == input_hash

    levels = load_level_plan(config.level_plan, (20, 10))
    scaled = ScaledSpace(config.scale)
    overlap = compute_overlap(levels["01"], levels["02"], scaled)
    assert overlap is not None
    canvas_size = tuple(read_json(root / "run.json")["canvas_size"])
    first_transform = build_transform(levels["01"], scaled, config.canvas, canvas_size)
    second_transform = build_transform(levels["02"], scaled, config.canvas, canvas_size)
    first_x, first_y = first_transform.global_to_local(*overlap.global_box[:2])
    second_x, second_y = second_transform.global_to_local(*overlap.global_box[:2])
    with Image.open(level_paths(root, "01")["root"] / "accepted" / "image.png") as first:
        first_region = np.asarray(
            first.convert("RGBA").crop(
                (first_x, first_y, first_x + overlap.width, first_y + overlap.height)
            )
        )
    with Image.open(second_paths["generation_input"]) as second:
        second_region = np.asarray(
            second.convert("RGBA").crop(
                (second_x, second_y, second_x + overlap.width, second_y + overlap.height)
            )
        )
    active = overlap.pixels > 0
    assert np.array_equal(first_region[active], second_region[active])

    second_job = create_job(root, "02")
    with Image.open(second_job.input_path) as opened:
        tampered = opened.convert("RGBA")
    tampered_array = np.array(tampered)
    with Image.open(canvas_asset(second_job.directory, "locked_mask")) as locked:
        tampered_array[np.asarray(locked) > 0] = (255, 0, 0, 255)
    tampered_path = tmp_path / "tampered.png"
    Image.fromarray(tampered_array, mode="RGBA").save(tampered_path)
    result = ingest_result(root, "02", tampered_path, attempt=second_job.attempt, auto_accept=True)
    assert result["state"] == "accepted"
    assert validate_run(root)["valid"] is True


def test_selector_and_real_plan_contract():
    assert parse_level_selector("01-03,05,03", {"01", "02", "03", "05"}) == [
        "01",
        "02",
        "03",
        "05",
    ]
    repo = Path(__file__).resolve().parents[2]
    plan = load_level_plan(
        repo / "levels" / "Frostreach" / "proposed_25_level_areas.csv",
        (1536, 1024),
    )
    assert len(plan) == 25
    assert plan["04"].name == "Howling Waste"
    assert plan["03"].connection_to("04") is not None


def test_automatic_batch_refreshes_between_selected_levels(tmp_path: Path):
    config_path = _write_fixture(tmp_path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["execution"]["approval_mode"] = "automatic"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config = load_config(config_path)
    prepare_run(config)
    summary = run_batch(config.output_root, ["01", "02"])
    assert summary["status"] == "finished"
    assert [item["state"] for item in summary["results"]] == ["accepted", "accepted"]
    run = read_json(config.output_root / "run.json")
    assert run["levels"]["01"]["state"] == "accepted"
    assert run["levels"]["02"]["state"] == "accepted"
    assert validate_run(config.output_root)["valid"] is True


def test_batch_records_provider_failure_after_configured_retries(tmp_path: Path, monkeypatch):
    config_path = _write_fixture(tmp_path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    raw["execution"]["retry_limit"] = 2
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    config = load_config(config_path)
    prepare_run(config)

    class FailingBackend:
        calls = 0

        def generate(self, job):
            self.calls += 1
            raise RuntimeError("provider unavailable")

    backend = FailingBackend()
    monkeypatch.setattr(
        "tools.painted_map_pipeline.world_levels.batch_runner.make_generation_backend",
        lambda generation: backend,
    )
    summary = run_batch(config.output_root, ["01"])
    assert summary["status"] == "failed"
    assert backend.calls == 3
    run = read_json(config.output_root / "run.json")
    assert run["levels"]["01"]["state"] == "failed"
    assert run["levels"]["01"]["error"] == "provider unavailable"
