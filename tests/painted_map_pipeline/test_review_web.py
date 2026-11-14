"""The level review page, without a browser: a fake orchestrate call, a real run on disk."""

from __future__ import annotations

import json
import shutil
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from test_world_levels import _write_fixture
from tools.painted_map_pipeline.world_levels.config import load_config
from tools.painted_map_pipeline.world_levels.job_builder import canvas_asset, create_job
from tools.painted_map_pipeline.world_levels.package_builder import prepare_run
from tools.painted_map_pipeline.world_levels.package_refresher import refresh_level
from tools.painted_map_pipeline.world_levels.result_ingest import ingest_result
from tools.painted_map_pipeline.world_levels.review_run import (
    CommandFailed,
    attempt_of,
    reingest_args,
)
from tools.painted_map_pipeline.world_levels.review_web import (
    REPO,
    ReviewPage,
    _call_here,
    _OwnPortServer,
    make_handler,
)
from tools.painted_map_pipeline.world_levels.state_store import read_json


class FakeCall:
    """Records each orchestrate command; answers with ``payload`` or raises ``refuse``."""

    def __init__(self, payload=None, refuse=None):
        self.calls: list[tuple[list[str], dict]] = []
        self.payload = payload or {}
        self.refuse = refuse

    def __call__(self, *args, **kwargs):
        self.calls.append((list(args), kwargs))
        if self.refuse:
            raise CommandFailed(self.refuse)
        return self.payload


def _run(tmp_path):
    """01 accepted; 02 with two attempts, each with its own generated.png."""
    config = load_config(_write_fixture(tmp_path))
    prepare_run(config)
    root = config.output_root
    refresh_level(root, "01")
    first = create_job(root, "01")
    ingest_result(root, "01", first.input_path, attempt=first.attempt, auto_accept=True)
    for _ in range(2):
        job = create_job(root, "02")
        shutil.copy2(job.input_path, job.directory / "generated.png")
    return root


def _page(tmp_path, call=None, **kwargs):
    root = _run(tmp_path)
    return ReviewPage(root, ["01", "02"], call=call or FakeCall(), **kwargs)


def _wait(page):
    for _ in range(200):
        if not page.run.running:
            return page.run.snapshot()
        time.sleep(0.02)
    raise AssertionError("the command never finished")


def test_reingest_args_match_the_console_and_carry_the_offset(tmp_path):
    args = reingest_args(tmp_path, "02", image="g.png", attempt=3, feather=8, align=True)
    assert args == ["ingest", str(tmp_path), "--level", "02", "--image", "g.png",
                    "--attempt", "3", "--feather", "8", "--align-colours"]
    shifted = reingest_args(tmp_path, "02", image="g.png", attempt=3, offset=(-3, 2), padding=False)
    assert shifted[-3:] == ["--padding", "none", "--padding-offset=-3,2"]


def test_attempt_of_reads_the_folder_name():
    assert attempt_of("x/attempts/attempt_012/placement_003.png") == 12
    assert attempt_of("x/jobs/attempt_002/generated.png") == 2
    assert attempt_of("x/accepted/image.png") is None


def test_place_runs_ingest_on_the_pinned_attempt_with_the_offset(tmp_path):
    call = FakeCall({"placement_path": "x/colour_align_001.png"})
    page = _page(tmp_path, call)
    info = page.level_info("02", 1)
    assert info["attempts"] == [1, 2] and info["attempt"] == 1

    page.place("02", {"attempt": 1, "feather": 0, "align": True, "padding": True, "offset": [2, -1]})
    assert _wait(page)["error"] is None

    args, kwargs = call.calls[0]
    raw = page.root / "levels" / "02" / "jobs" / "attempt_001" / "generated.png"
    assert args == reingest_args(page.root, "02", image=raw, attempt=1, align=True, offset=(2, -1))
    assert kwargs == {"fatal": False, "cwd": REPO}
    assert page.level_info("02")["settings"]["offset"] == [2, -1]
    assert page.level_info("02")["attempt"] == 1


def test_a_refused_place_leaves_the_settings_as_they_were(tmp_path):
    page = _page(tmp_path, FakeCall(refuse="warp refused: polygon fills the canvas"))
    before = dict(page.level_info("02", 2)["settings"])
    page.place("02", {"attempt": 2, "warp": True, "padding": True, "offset": [1, 1]})
    snapshot = _wait(page)
    assert snapshot["error"] == "REFUSED: warp refused: polygon fills the canvas"
    assert page.level_info("02", 2)["settings"] == before


def test_an_offset_on_a_frame_attempt_is_refused_before_any_command(tmp_path):
    call = FakeCall()
    page = _page(tmp_path, call)
    job_path = page.root / "levels" / "02" / "jobs" / "attempt_002" / "job.json"
    job = read_json(job_path)
    job["renderer"] = "frame"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    with pytest.raises(ValueError, match="needs the warp renderer"):
        page.place("02", {"attempt": 2, "offset": [1, 0]})
    assert call.calls == []


def test_images_come_from_the_pinned_attempt(tmp_path):
    page = _page(tmp_path)
    assert page.image("02", "raw", 1).parent.name == "attempt_001"
    assert page.image("02", "raw", 2).parent.name == "attempt_002"


def test_the_padding_image_is_transparent_outside_the_mask(tmp_path):
    page = _page(tmp_path)
    with Image.open(__import__("io").BytesIO(page.padding_png("02", 1))) as opened:
        alpha = np.asarray(opened.convert("RGBA"))[..., 3]
    job_dir = page.root / "levels" / "02" / "jobs" / "attempt_001"
    with Image.open(canvas_asset(job_dir, "locked_mask")) as mask:
        assert np.array_equal(alpha, np.asarray(mask.convert("L")))
    assert alpha.any()


def test_generate_sends_the_retry_and_pins_the_new_attempt(tmp_path):
    call = FakeCall()
    page = _page(tmp_path, call, prompt_file="p.txt")
    produced = page.root / "levels" / "02" / "attempts" / "attempt_002" / "current.png"
    call.payload = {"results": [{"level_id": "02", "attempt": 2, "placement_path": str(produced)}]}
    page.generate("02", {"retry": True, "reason": "too dark", "image": "", "note": ""})
    assert _wait(page)["error"] is None
    args = call.calls[0][0]
    assert args == ["run", str(page.root), "--levels", "02", "--prompt-file", "p.txt",
                    "--retry-reason", "too dark"]
    assert page.level_info("02")["attempt"] == 2


def test_a_failed_generation_is_reported(tmp_path):
    page = _page(tmp_path, FakeCall({"results": [{"level_id": "02", "state": "failed",
                                                   "error": "missing API key"}]}))
    page.generate("02", {})
    assert _wait(page)["error"] == "ValueError: GENERATION FAILED: missing API key"


@pytest.fixture
def server(tmp_path):
    page = _page(tmp_path)
    httpd = _OwnPortServer(("127.0.0.1", 0), make_handler(page))
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield page, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _get(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.read(), error.headers


def test_routes(server):
    page, base = server
    status, body, _ = _get(f"{base}/api/levels")
    assert status == 200 and [lv["id"] for lv in json.loads(body)["levels"]] == ["01", "02"]
    status, body, _ = _get(f"{base}/api/level/02?attempt=1")
    info = json.loads(body)
    assert status == 200 and info["attempt"] == 1 and info["has_padding"]
    status, body, headers = _get(f"{base}/api/level/02/image/padding?attempt=1&v=1")
    assert status == 200 and headers["Content-Type"] == "image/png" and body[:4] == b"\x89PNG"
    assert "max-age" in headers["Cache-Control"]
    assert _get(f"{base}/api/level/99")[0] == 404
    assert _get(f"{base}/api/level/02/image/raw")[0] == 400
    status, body, _ = _get(f"{base}/")
    assert status == 200 and b"Level review" in body


def test_every_route_is_refused_while_a_command_runs(server):
    page, base = server
    page.run.start("02", "busy")
    try:
        for path, body in [("level/02/place", {"attempt": 1}), ("level/02/checks", {"attempt": 1}),
                           ("level/02/generate", {}), ("level/02/accept", {"attempt": 1}),
                           ("level/02?attempt=1", None)]:
            assert _get(f"{base}/api/{path}", body)[0] == 409, path
        status, body, _ = _get(f"{base}/api/progress")
        assert status == 200 and json.loads(body)["running"]
    finally:
        page.run.update(running=False)


def test_an_old_unlabelled_alignment_does_not_carry_the_old_method_over(tmp_path):
    page = _page(tmp_path)
    job_path = page.root / "levels" / "02" / "jobs" / "attempt_001" / "job.json"
    job = read_json(job_path)
    job.update({"placement_path": "x.png", "placement_align_colours": True,
                "placement_colour_alignment": {"strength": 1.0}})
    job_path.write_text(json.dumps(job), encoding="utf-8")
    assert page.level_info("02", 1)["settings"]["colour_method"] == "match"


def test_place_passes_the_swap_method_when_asked(tmp_path):
    call = FakeCall({"placement_path": "x/colour_align_001.png"})
    page = _page(tmp_path, call)
    page.place("02", {"attempt": 1, "align": True, "colour_method": "swap"})
    assert _wait(page)["error"] is None
    assert call.calls[0][0][-2:] == ["--colour-method", "swap"]


def test_the_in_process_call_returns_the_printed_json():
    def main(argv):
        print("working...")
        print(json.dumps({"placement_path": "/x/placement_003.png", "argv": argv}))
        print("open: /x/placement_003.png")

    payload = _call_here("ingest", "root", "--level", "06", main=main)
    assert payload == {"placement_path": "/x/placement_003.png",
                       "argv": ["ingest", "root", "--level", "06"]}


def test_the_in_process_call_turns_errors_and_exits_into_refusals():
    def stale(argv):
        raise ValueError("job context is stale; refresh and create a new job")

    def bad_flag(argv):
        raise SystemExit(2)

    def done(argv):
        raise SystemExit(0)

    with pytest.raises(CommandFailed, match="ValueError: job context is stale"):
        _call_here("ingest", main=stale)
    with pytest.raises(CommandFailed, match="ingest failed"):
        _call_here("ingest", main=bad_flag)
    assert _call_here("ingest", main=done) == {}


def test_generate_keeps_its_own_call_when_one_is_given(tmp_path):
    place_call, generate_call = FakeCall(), FakeCall(payload={"results": []})
    page = _page(tmp_path, call=place_call, generate_call=generate_call)
    page.generate("02", {})
    _wait(page)
    assert generate_call.calls and not place_call.calls
