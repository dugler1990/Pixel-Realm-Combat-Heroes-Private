"""End-to-end runs under each renderer, and the geometry they must agree on."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.painted_map_pipeline.world_levels.config import load_config
from tools.painted_map_pipeline.world_levels.job_builder import canvas_asset, create_job
from tools.painted_map_pipeline.world_levels.package_builder import level_paths, prepare_run
from tools.painted_map_pipeline.world_levels.package_refresher import refresh_level
from tools.painted_map_pipeline.world_levels.result_ingest import ingest_result
from tools.painted_map_pipeline.world_levels.state_store import read_json, sha256_file
from tools.painted_map_pipeline.world_levels.validate_continuity import validate_run

# These test directories are not packages, so pytest puts each test file's own directory
# on sys.path and the sibling module imports bare.
from test_world_levels import _write_fixture

FRAME = {"provider": "copy", "renderer": "frame"}


def _run(tmp_path: Path, generation: dict | None = None, name: str = ""):
    config = load_config(_write_fixture(tmp_path, generation=generation, name=name))
    prepare_run(config)
    return config


def _generate(root: Path, level_id: str) -> dict:
    """Take a level to accepted, standing the job's own input in for a model response.

    The input is copied to ``generated.png`` first, where a real backend would leave it, so
    the attempt on disk has the same shape the scoring path expects.
    """
    refresh_level(root, level_id)
    job = create_job(root, level_id)
    shutil.copy2(job.input_path, job.output_path)
    return ingest_result(root, level_id, job.output_path, attempt=job.attempt, auto_accept=True)


def test_frame_run_tiles_exactly(tmp_path: Path):
    config = _run(tmp_path, FRAME)
    root = config.output_root
    for level_id in ("01", "02"):
        assert _generate(root, level_id)["state"] == "accepted"

    report = validate_run(root)
    assert report["valid"] is True
    assert report["accepted_pairs"]
    assert all(pair["differing_pixels"] == 0 for pair in report["accepted_pairs"])


def test_frame_run_records_its_renderer_on_every_job(tmp_path: Path):
    config = _run(tmp_path, FRAME)
    root = config.output_root
    assert read_json(root / "run.json")["renderer"] == "frame"

    refresh_level(root, "01")
    job = create_job(root, "01")
    manifest = read_json(job.manifest_path)
    assert manifest["renderer"] == "frame"
    # Job assets are deliberately mixed-size: what was sent is frame-sized, the canvas-space
    # assets the ingest path reads back afterwards are not.
    assert manifest["input_size"] == manifest["frame"]["size"]
    assert manifest["input_size"] != manifest["canvas_size"]
    with Image.open(job.input_path) as sent:
        assert list(sent.size) == manifest["input_size"]
    with Image.open(canvas_asset(job.directory, "generation_mask")) as mask:
        assert list(mask.size) == manifest["canvas_size"]


def test_accepted_art_is_cut_exactly_to_the_polygon(tmp_path: Path):
    config = _run(tmp_path, FRAME)
    root = config.output_root
    _generate(root, "01")

    paths = level_paths(root, "01")
    accepted = np.asarray(Image.open(paths["root"] / "accepted" / "image.png").convert("RGBA"))
    mask = np.asarray(Image.open(paths["generation_mask"]).convert("L")) > 0
    # Geometry by construction: nothing outside the polygon survives, and no rescale or warp
    # ran to put it there.
    assert np.all(accepted[~mask] == np.array(config.outside_color))


def test_both_renderers_share_identical_canvas_geometry(tmp_path: Path):
    """Verification step 5.

    The frame is derived rather than folded back into the crop box, so switching renderer
    must not move a single canvas coordinate. This is the test that catches frame expansion
    leaking into the shared geometry.
    """
    warp = _run(tmp_path, {"provider": "copy"}, name="_warp")
    frame = _run(tmp_path, FRAME, name="_frame")

    warp_run, frame_run = read_json(warp.output_root / "run.json"), read_json(frame.output_root / "run.json")
    assert warp_run["canvas_size"] == frame_run["canvas_size"]

    for level_id in ("01", "02"):
        warp_paths, frame_paths = level_paths(warp.output_root, level_id), level_paths(frame.output_root, level_id)
        warp_manifest, frame_manifest = read_json(warp_paths["manifest"]), read_json(frame_paths["manifest"])
        assert warp_manifest["transform"] == frame_manifest["transform"], level_id
        for asset in ("generation_mask", "core_mask", "outside_mask", "dense_template"):
            assert sha256_file(warp_paths[asset]) == sha256_file(frame_paths[asset]), (level_id, asset)


def test_preparing_over_a_root_with_a_different_renderer_is_refused(tmp_path: Path):
    _run(tmp_path, {"provider": "copy"})
    # Same output_root, different renderer: every manifest would keep geometry from the other
    # method, because prepare reuses manifests that already exist.
    switched = load_config(_write_fixture(tmp_path, generation=FRAME))
    with pytest.raises(ValueError, match="use a separate output_root"):
        prepare_run(switched)


def test_frame_renderer_refuses_automatic_approval(tmp_path: Path):
    # No footprint gate exists under the frame renderer, so a human looking at each draw is
    # the only thing standing between a bad one and every neighbour that copies from it.
    config_path = _write_fixture(tmp_path, generation=FRAME)
    raw = config_path.read_text(encoding="utf-8").replace('"manual"', '"automatic"')
    config_path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="requires execution.approval_mode 'manual'"):
        load_config(config_path)


def test_score_labels_the_renderer_and_declines_to_score_a_frame_attempt(tmp_path: Path):
    from tools.painted_map_pipeline.world_levels.score_attempts import score_level

    config = _run(tmp_path, FRAME)
    root = config.output_root
    _generate(root, "01")

    scored = score_level(root, "01")
    entry = scored["attempts"][0]
    assert entry["renderer"] == "frame"
    # Nothing to score a silhouette against, and a number here would invite comparing it
    # against warp attempts that measure something else.
    assert entry["footprint_iou"] is None
    assert "does not apply" in entry["note"]


def test_score_still_reports_a_footprint_for_a_warp_attempt(tmp_path: Path):
    from tools.painted_map_pipeline.world_levels.score_attempts import score_level

    config = _run(tmp_path, {"provider": "copy"})
    root = config.output_root
    _generate(root, "01")

    entry = score_level(root, "01")["attempts"][0]
    assert entry["renderer"] == "warp"
    assert entry["footprint_iou"] == pytest.approx(1.0)
