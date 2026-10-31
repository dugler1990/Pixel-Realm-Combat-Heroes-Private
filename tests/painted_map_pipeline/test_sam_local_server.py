"""`sam_local.segment` through the local SAM3 server, against a fake one: no GPU, no SAM.

Every process start is faked, so nothing here can launch the real server or `run_chunk.py`.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from PIL import Image

from tools.painted_map_pipeline.interiors import sam_local

POLYGONS = [{"class": "stone border", "prompt": "stone border", "confidence": 0.9,
             "points": [[0, 0], [10, 0], [10, 10]]}]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class FakeServer:
    """Answers like sam3local's server. `replies` are the statuses its /run gives in turn (200
    once they run out); a 409 shuts it down after replying, as the real one does."""

    def __init__(self, port, replies=()):
        self.requests = []
        self.replies = list(replies)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, status, body):
                data = json.dumps(body).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._reply(200, {"service": "sam3local", "pid": 1, "busy": False})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                status = fake.replies.pop(0) if fake.replies else 200
                if status == 409:
                    self._reply(409, {"stale": "sam3local changed since the server started"})
                    threading.Thread(target=fake.stop, daemon=True).start()
                    return
                if status != 200:
                    self._reply(status, {"error": "CUDA out of memory", "log": "partial"})
                    return
                result = Path(body["out"]) / body["chunk_id"] / "polygons.json"
                result.parent.mkdir(parents=True, exist_ok=True)
                result.write_text(json.dumps({"polygons": POLYGONS}), encoding="utf-8")
                self._reply(200, {"code": 0, "log": f"ran {body['chunk_id']}"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def sam(tmp_path, monkeypatch):
    """A stand-in sam3local checkout whose config names a free port, and an image to send."""
    root = tmp_path / "sam3local"
    for name in ("scripts/run_chunk.py", "scripts/serve.py", ".venv/Scripts/python.exe"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("", encoding="utf-8")
    port = _free_port()
    (root / "config").mkdir()
    (root / "config" / "server.json").write_text(
        json.dumps({"port": port, "idle_minutes": 15}), encoding="utf-8")
    image = tmp_path / "crop.png"
    Image.new("RGB", (64, 48)).save(image)
    monkeypatch.setenv("SAM3LOCAL_ROOT", str(root))
    monkeypatch.delenv("SAM3LOCAL_SERVER", raising=False)
    started, ran = [], []

    def no_run(command, **kwargs):
        ran.append(command)
        raise AssertionError("run_chunk.py was started")

    monkeypatch.setattr(sam_local.subprocess, "run", no_run)
    monkeypatch.setattr(sam_local, "SERVER_START_TIMEOUT", 5)
    yield {"root": root, "port": port, "image": image, "work": tmp_path / "work",
           "started": started, "ran": ran}


def _fake_popen(monkeypatch, sam, *, exits=None, servers=None):
    """Starting the server: either a fake server comes up on the port, or the child exits."""

    class Child:
        def __init__(self, command, **kwargs):
            sam["started"].append(command)
            if exits is None:
                servers.append(FakeServer(sam["port"]))

        def poll(self):
            return exits

    monkeypatch.setattr(sam_local.subprocess, "Popen", Child)


def test_a_call_goes_to_the_running_server(sam, monkeypatch):
    server = FakeServer(sam["port"])
    _fake_popen(monkeypatch, sam, exits=1)
    try:
        polygons = sam_local.segment(sam["image"], ["stone border"], sam["work"],
                                     chunk_id="walls_x", tile=False)
    finally:
        server.stop()

    assert polygons == POLYGONS
    assert not sam["started"] and not sam["ran"], "nothing started: the server was up"
    sent = server.requests[0]
    assert (sent["chunk_id"], sent["tile"]) == ("walls_x", False)
    assert Path(sent["out"]) == sam["work"].resolve()
    assert Path(sent["image"]) == sam["image"].resolve()
    assert (sam["work"] / "walls_x" / "request.json").exists(), "cached like any run"


def test_a_server_that_is_not_up_is_started_then_used(sam, monkeypatch):
    servers = []
    _fake_popen(monkeypatch, sam, servers=servers)
    try:
        polygons = sam_local.segment(sam["image"], ["stone border"], sam["work"],
                                     chunk_id="walls_x", tile=False)
    finally:
        for server in servers:
            server.stop()

    assert polygons == POLYGONS
    (command,) = sam["started"]
    assert Path(command[1]).name == "serve.py" and command[2] == "start"
    assert Path(command[command.index("--log") + 1]) == sam["root"] / "output" / "server.log"
    assert not sam["ran"]


def test_a_server_that_cannot_start_is_an_error_naming_its_log(sam, monkeypatch):
    """Loud, not a quiet fall back to loading the model per call."""
    _fake_popen(monkeypatch, sam, exits=1)
    with pytest.raises(sam_local.SamLocalError, match="server.log"):
        sam_local.segment(sam["image"], ["stone border"], sam["work"], chunk_id="walls_x",
                          tile=False)
    assert not sam["ran"]


def test_an_out_of_date_server_is_replaced_once(sam, monkeypatch):
    servers = []
    old = FakeServer(sam["port"], replies=[409])
    _fake_popen(monkeypatch, sam, servers=servers)
    try:
        polygons = sam_local.segment(sam["image"], ["stone border"], sam["work"],
                                     chunk_id="walls_x", tile=False)
    finally:
        for server in servers:
            server.stop()

    assert polygons == POLYGONS
    assert len(old.requests) == 1 and len(sam["started"]) == 1
    assert len(servers[0].requests) == 1, "the retry went to the fresh server"


def test_a_failed_run_on_the_server_raises_with_its_log(sam, monkeypatch):
    server = FakeServer(sam["port"], replies=[500])
    _fake_popen(monkeypatch, sam, exits=1)
    try:
        with pytest.raises(sam_local.SamLocalError, match="CUDA out of memory"):
            sam_local.segment(sam["image"], ["stone border"], sam["work"], chunk_id="walls_x",
                              tile=False)
    finally:
        server.stop()
    assert not sam["started"] and not sam["ran"]


@pytest.mark.parametrize("switched_off", ["env", "no serve.py"])
def test_without_the_server_each_call_is_its_own_process(sam, monkeypatch, switched_off):
    if switched_off == "env":
        monkeypatch.setenv("SAM3LOCAL_SERVER", "0")
    else:
        (sam["root"] / "scripts" / "serve.py").unlink()
    _fake_popen(monkeypatch, sam, exits=1)

    def run_chunk(command, **kwargs):
        sam["ran"].append(command)
        out, chunk = Path(command[command.index("--out") + 1]), command[command.index("--chunk-id") + 1]
        (out / chunk).mkdir(parents=True, exist_ok=True)
        (out / chunk / "polygons.json").write_text(json.dumps({"polygons": POLYGONS}))
        return type("Finished", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(sam_local.subprocess, "run", run_chunk)
    polygons = sam_local.segment(sam["image"], ["stone border"], sam["work"], chunk_id="walls_x",
                                 tile=False)

    assert polygons == POLYGONS
    assert len(sam["ran"]) == 1 and "--no-tile" in sam["ran"][0]
    assert not sam["started"], "no server was asked for"
