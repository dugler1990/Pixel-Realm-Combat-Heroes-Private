"""Tests for reopening a finished level: force, and the refine pass."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tools.painted_map_pipeline.world_levels.config import load_config
from tools.painted_map_pipeline.world_levels.job_builder import create_job
from tools.painted_map_pipeline.world_levels.package_builder import level_paths, prepare_run
from tools.painted_map_pipeline.world_levels.package_refresher import refresh_level
from tools.painted_map_pipeline.world_levels.result_ingest import ingest_result

# These test directories are not packages, so pytest puts each test file's own directory
# on sys.path and the sibling module imports bare.
from test_world_levels import _write_fixture


def _accept_first_level(tmp_path: Path):
    """Prepare a fixture run and take level 01 through to accepted."""
    config = load_config(_write_fixture(tmp_path))
    prepare_run(config)
    root = config.output_root
    refresh_level(root, "01")
    job = create_job(root, "01")
    # A real generation comes back different from what was sent; with the warp off by default
    # nothing else would make the accepted art differ from the template, and the refine pass
    # would have nothing to be a pass over.
    with Image.open(job.input_path) as opened:
        drawn = np.asarray(opened.convert("RGBA")).copy()
    painted = drawn[..., :3].sum(axis=2) > 40      # leave the black background black
    drawn[painted, :3] = np.clip(drawn[painted, :3].astype(np.int16) + 40, 0, 255).astype(np.uint8)
    generated = tmp_path / "generated.png"
    Image.fromarray(drawn, mode="RGBA").save(generated)
    ingest_result(root, "01", generated, attempt=job.attempt, auto_accept=True)
    return config, root


def test_refresh_skips_accepted_without_force(tmp_path: Path):
    _, root = _accept_first_level(tmp_path)
    assert refresh_level(root, "01") == {"level_id": "01", "skipped": "accepted"}


def test_force_reopens_an_accepted_level(tmp_path: Path):
    _, root = _accept_first_level(tmp_path)
    result = refresh_level(root, "01", force=True)
    assert result.get("skipped") is None
    assert result["level_id"] == "01"


def test_refine_input_is_the_accepted_art_inside_the_polygon(tmp_path: Path):
    _, root = _accept_first_level(tmp_path)
    paths = level_paths(root, "01")

    refresh_level(root, "01", force=True)
    from_template = np.asarray(Image.open(paths["generation_input"]).convert("RGB"))

    refresh_level(root, "01", force=True, refine=True)
    from_accepted = np.asarray(Image.open(paths["generation_input"]).convert("RGB"))

    accepted = np.asarray(Image.open(paths["root"] / "accepted" / "image.png").convert("RGB"))
    dense = np.asarray(Image.open(paths["dense_template"]).convert("RGB"))
    mask = np.asarray(Image.open(paths["generation_mask"]).convert("L")) > 0

    # Inside the polygon the refine input is the level's own finished art.
    assert np.array_equal(from_accepted[mask], accepted[mask])
    # Outside it the soft world map survives, so the input stays dense for whichever
    # renderer consumes it -- the warp one masks it away, the frame one crops it.
    assert np.array_equal(from_accepted[~mask], dense[~mask])
    assert not np.array_equal(from_accepted, from_template)


def test_refine_without_an_accepted_image_is_refused(tmp_path: Path):
    config = load_config(_write_fixture(tmp_path))
    prepare_run(config)
    with pytest.raises(FileNotFoundError, match="no accepted image to refine"):
        refresh_level(config.output_root, "01", force=True, refine=True)


def test_refine_job_records_itself_and_reuses_the_attempt_series(tmp_path: Path):
    _, root = _accept_first_level(tmp_path)
    refresh_level(root, "01", force=True, refine=True)
    job = create_job(root, "01", refine=True)

    from tools.painted_map_pipeline.world_levels.state_store import read_json

    manifest = read_json(job.manifest_path)
    assert manifest["refine"] is True
    assert job.attempt == 2
