"""The level studio, without a paid image call and without a browser."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from tools.painted_map_pipeline.world_levels import studio as studio_mod
from tools.painted_map_pipeline.world_levels.review_web import _OwnPortServer
from tools.painted_map_pipeline.world_levels.studio import Studio, make_handler


def _wait(studio: Studio) -> dict:
    for _ in range(200):
        snapshot = studio.job.snapshot()
        if not snapshot.get("running"):
            return snapshot
        time.sleep(0.02)
    raise AssertionError("the command never finished")


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "generated" / "world_levels" / "src"
    accepted = root / "levels" / "07" / "accepted"
    accepted.mkdir(parents=True)
    Image.new("RGB", (64, 48), (90, 70, 40)).save(accepted / "image.png")
    (root / "config.json").write_text(json.dumps({
        "generation": {"model": "gpt-image-2", "quality": "high", "provider": "openai"},
    }), encoding="utf-8")
    (root / "run.json").write_text(json.dumps({"levels": {"07": {"state": "accepted"}}}), encoding="utf-8")
    return root


def _grid_land(tmp_path: Path) -> Path:
    scale = tmp_path / "generated" / "world_levels" / "icegrid" / "scale"
    scale.mkdir(parents=True)
    image = Image.new("RGB", (80, 48), (0, 0, 0))
    ImageDraw.Draw(image).rectangle([1, 1, 78, 46], fill=(200, 180, 120))
    image.save(scale / "background_snapped.png")
    (scale / "landmass_polygon.json").write_text(json.dumps({
        "polygon": [[1, 1], [78, 1], [78, 46], [1, 46]],
    }), encoding="utf-8")
    (scale.parent / "studio.json").write_text("{}\n", encoding="utf-8")
    return scale.parent


def _server(studio: Studio):
    httpd = _OwnPortServer(("127.0.0.1", 0), make_handler(studio))
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _request(url: str, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers


def test_compose_keeps_the_attempt_and_does_not_rewrite_config(tmp_path, monkeypatch):
    root = _source(tmp_path)
    seen = {}

    def fake(**kwargs):
        seen["config"] = dict(kwargs["config"])
        Image.new("RGB", (kwargs["width"], kwargs["height"]), (20, 80, 40)).save(kwargs["output_path"])
        return {}

    monkeypatch.setattr(
        "tools.painted_map_pipeline.world_levels.compose.edit_image", fake
    )
    studio = Studio(tmp_path)
    httpd, base = _server(studio)
    before = (root / "config.json").read_bytes()
    try:
        status, body, _ = _request(f"{base}/api/studio/compose", {
            "run": "src", "level": "07", "prompt": "Keep the outline. Open ice.",
            "quality": "low", "model": "gpt-image-2", "player_px": None,
        })
        assert status == 200, body
        snapshot = _wait(studio)
        assert snapshot["error"] is None, snapshot
        attempt = root / "levels" / "07" / "composed" / "attempt_001" / "composed.png"
        assert attempt.is_file()
        assert seen["config"]["quality"] == "low"
        assert seen["config"]["model"] == "gpt-image-2"
        assert seen["config"]["provider"] == "openai"
        assert (root / "config.json").read_bytes() == before

        status, body, _ = _request(f"{base}/api/studio/accept", {"run": "src", "level": "07", "attempt": 1})
        assert status == 200, body
        locked = root / "levels" / "07" / "composed" / "composed.png"
        assert locked.read_bytes() == attempt.read_bytes()
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_an_image_outside_the_roots_is_refused(tmp_path):
    studio = Studio(tmp_path)
    outside = tmp_path / "secret.png"
    Image.new("RGB", (2, 2), (1, 2, 3)).save(outside)
    allowed_run = tmp_path / "generated" / "world_levels" / "dot.png"
    allowed_run.parent.mkdir(parents=True)
    Image.new("RGB", (2, 2), (4, 5, 6)).save(allowed_run)
    world = tmp_path / "levels" / "Frostreach" / "world.png"
    world.parent.mkdir(parents=True)
    Image.new("RGB", (2, 2), (7, 8, 9)).save(world)
    nested = world.parent / "sunspine" / "background.png"
    nested.parent.mkdir()
    Image.new("RGB", (2, 2), (0, 0, 0)).save(nested)

    httpd, base = _server(studio)
    try:
        assert _request(f"{base}/api/studio/img?path={urllib.parse.quote(str(outside))}")[0] == 400
        escaped = tmp_path / "generated" / "world_levels" / ".." / "secret.png"
        assert _request(f"{base}/api/studio/img?path={urllib.parse.quote(str(escaped))}")[0] == 400
        assert _request(f"{base}/api/studio/img?path={urllib.parse.quote(str(nested))}")[0] == 400
        status, body, headers = _request(f"{base}/api/studio/img?path={urllib.parse.quote(str(allowed_run))}")
        assert status == 200 and body[:4] == b"\x89PNG" and headers["Content-Type"] == "image/png"
        assert _request(f"{base}/api/studio/img?path={urllib.parse.quote(str(world))}")[0] == 200
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_a_second_command_is_refused_while_one_runs(tmp_path):
    studio = Studio(tmp_path)
    hold = threading.Event()

    def work():
        hold.wait(5)
        return "done"

    httpd, base = _server(studio)
    studio.start("hold", work)
    try:
        status, body, _ = _request(f"{base}/api/studio/compose", {"run": "src", "level": "07", "prompt": "x"})
        assert status == 409, body
        status, _, _ = _request(f"{base}/api/studio/status")
        assert status == 200
    finally:
        hold.set()
        httpd.shutdown()
        httpd.server_close()


def test_grid_route_writes_a_plan_and_does_not_snap_or_prepare(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(studio_mod, "snap_map", lambda *a, **k: called.append("snap"))
    monkeypatch.setattr(studio_mod, "prepare_run", lambda *a, **k: called.append("prepare"))
    job = _grid_land(tmp_path)
    before = (job / "scale" / "background_snapped.png").read_bytes()
    studio = Studio(tmp_path)
    httpd, base = _server(studio)
    try:
        status, body, _ = _request(f"{base}/api/studio/grid", {
            "name": "icegrid", "cols": 2, "rows": 2, "region": "Ice", "name_prefix": "Floe",
            "overlap_buffer": 4, "crop_margin": 1,
        })
        assert status == 200, body
        snapshot = _wait(studio)
        assert snapshot["error"] is None, snapshot
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert called == []
    assert (job / "plan.csv").is_file()
    assert (job / "plan_overlay.png").is_file()
    grid = json.loads((job / "grid.json").read_text(encoding="utf-8"))
    assert grid["levels"] >= 1 and grid["cols"] == 2
    assert not (job / "run.json").exists()
    assert (job / "scale" / "background_snapped.png").read_bytes() == before


def test_the_front_page_is_the_studio_and_review_links_back(tmp_path):
    studio = Studio(tmp_path)
    httpd, base = _server(studio)
    try:
        status, body, _ = _request(f"{base}/")
        assert status == 200 and b"Level studio" in body
        status, body, _ = _request(f"{base}/review")
        assert status == 200 and b"Level review" in body and b"Steps" in body
    finally:
        httpd.shutdown()
        httpd.server_close()
