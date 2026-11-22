"""HYPIR pod connect and one-level send. The remote is fake: no SSH, no network."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from PIL import Image

from tools.painted_map_pipeline.world_levels.pod_upscale import (
    ICE_PROMPT,
    INSTALL_SH,
    RUN_SH,
    PodError,
    parse_ssh_line,
    save_native,
    scp_argv,
    ssh_argv,
)
from tools.painted_map_pipeline.world_levels.review_web import ReviewPage, _OwnPortServer, make_handler
from test_review_web import _get, _page, _wait


class FakeRemote:
    def __init__(self, installed=False, fail=None):
        self.installed = installed
        self.fail = fail
        self.scripts: list[str] = []
        self.puts: list[str] = []

    def run(self, script, timeout=None):
        self.scripts.append(script)
        if self.fail and self.fail in script:
            raise PodError("pod refused")
        if "nvidia-smi" in script:
            return "CONNECTED\nGPU 0\n"
        if "echo MISSING" in script:
            return "READY\n" if self.installed else "MISSING\n"
        if "git clone" in script:
            self.installed = True
            return "install log\nREADY\n"
        if "test.py" in script:
            return "Done.\n"
        return ""

    def put(self, local, remote):
        self.puts.append(remote)

    def get(self, remote, local):
        local.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (12, 8), (4, 5, 6)).save(local)


def _line(key: Path, host="203.0.113.5", port=17432) -> str:
    return f"ssh root@{host} -p {port} -i {key}"


def _connected(tmp_path, remote=None):
    remote = remote or FakeRemote()
    key = tmp_path / "id_ed25519"
    key.write_text("not a key", encoding="utf-8")
    page = _page(tmp_path, remote_factory=lambda target: remote)
    return page, remote, _line(key)


def test_parse_reads_the_runpod_connect_line(tmp_path):
    key = tmp_path / "id_ed25519"
    target = parse_ssh_line(f"ssh root@203.0.113.5 -p 17432 -i {key}")
    assert (target.user, target.host, target.port, target.key) == ("root", "203.0.113.5", 17432, key)
    target = parse_ssh_line(f"ssh -i {key} -p 22 root@example.test")
    assert target.port == 22 and target.host == "example.test"
    windows = parse_ssh_line(r"ssh root@host -p 9 -i C:\Users\Douglas\.ssh\id_ed25519")
    assert windows.key == Path(r"C:\Users\Douglas\.ssh\id_ed25519")


def test_parse_rejects_a_line_that_is_not_a_connect_command():
    with pytest.raises(ValueError, match="starting with ssh"):
        parse_ssh_line("root@host -p 1 -i key")
    with pytest.raises(ValueError, match="port"):
        parse_ssh_line("ssh root@host -i key")
    with pytest.raises(ValueError, match="-i"):
        parse_ssh_line("ssh root@host -p 22")


def test_ssh_argv_is_batch_mode_and_does_not_run():
    target = parse_ssh_line(r"ssh root@203.0.113.5 -p 17432 -i C:\keys\id")
    argv = ssh_argv(target)
    assert "BatchMode=yes" in argv and "17432" in argv and argv[-1] == "root@203.0.113.5"
    copied = scp_argv(target, "a.png", "root@203.0.113.5:/tmp/a.png")
    assert "-P" in copied and "17432" in copied


def test_connect_installs_when_hypir_is_missing_and_skips_when_it_is_there(tmp_path):
    page, remote, line = _connected(tmp_path)
    page.connect_pod({"ssh": line})
    assert _wait(page)["error"] is None
    assert page.pod.snapshot()["phase"] == "ready"
    assert any("git clone" in script for script in remote.scripts)
    assert INSTALL_SH in remote.scripts

    again = FakeRemote(installed=True)
    page.remote_factory = lambda target: again
    page.connect_pod({"ssh": line})
    assert _wait(page)["error"] is None
    assert not any("git clone" in script for script in again.scripts)


def test_a_refused_pod_is_reported_and_leaves_the_session_idle(tmp_path):
    page, remote, line = _connected(tmp_path, FakeRemote(fail="nvidia-smi"))
    page.connect_pod({"ssh": line})
    assert _wait(page)["error"] == "pod refused"
    assert page.pod.snapshot()["phase"] == "idle"
    assert remote.puts == []


def test_a_missing_key_is_refused_before_any_remote_call(tmp_path):
    page = _page(tmp_path, remote_factory=lambda target: pytest.fail("remote was built"))
    with pytest.raises(ValueError, match="SSH key not found"):
        page.connect_pod({"ssh": "ssh root@203.0.113.5 -p 22 -i C:/no/such/key"})


def test_send_writes_the_2x_result_and_the_same_size_copy(tmp_path):
    page, remote, line = _connected(tmp_path, FakeRemote(installed=True))
    page.connect_pod({"ssh": line})
    assert _wait(page)["error"] is None
    source = page._upscale_source("01")
    assert source.name == "image.png" and source.parent.name == "accepted"
    assert page._upscale_source("02").name == "generated.png"

    page.run_upscale({"level": "02"})
    done = _wait(page)
    assert done["error"] is None and "hypir.png" in done["message"]
    assert remote.puts == ["/workspace/hypir/job/in/piece.png"]
    assert ICE_PROMPT in RUN_SH
    hypir = page.root / "levels" / "02" / "upscale" / "hypir.png"
    native = page.root / "levels" / "02" / "upscale" / "hypir_native.png"
    with Image.open(hypir) as got, Image.open(page._upscale_source("02")) as src, Image.open(native) as back:
        assert got.size == (12, 8)
        assert back.size == src.size
    assert page.upscale_image("02", "native") == native


def test_send_before_connect_is_refused(tmp_path):
    page = _page(tmp_path)
    with pytest.raises(ValueError, match="Connect"):
        page.run_upscale({"level": "02"})


def test_save_native_scales_the_result_back_to_the_source(tmp_path):
    source, hypir, dest = tmp_path / "s.png", tmp_path / "h.png", tmp_path / "n.png"
    Image.new("RGB", (6, 4), (9, 9, 9)).save(source)
    Image.new("RGB", (12, 8), (1, 2, 3)).save(hypir)
    save_native(source, hypir, dest)
    with Image.open(dest) as got:
        assert got.size == (6, 4)


def test_status_answers_while_a_command_is_running(tmp_path):
    page = _page(tmp_path)
    httpd = _OwnPortServer(("127.0.0.1", 0), make_handler(page))
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    page.run.start("02", "busy")
    try:
        status, body, _ = _get(f"{base}/api/upscale/status?level=02")
        data = json.loads(body)
        assert status == 200 and data["phase"] == "idle" and data["running"]
        assert _get(f"{base}/api/upscale/run", {"level": "02"})[0] == 409
    finally:
        page.run.update(running=False)
        httpd.shutdown()
        httpd.server_close()


def test_disconnect_does_not_claim_the_pod_was_stopped(tmp_path):
    page, remote, line = _connected(tmp_path, FakeRemote(installed=True))
    page.connect_pod({"ssh": line})
    _wait(page)
    text = page.disconnect_pod()["detail"]
    assert "RunPod" in text and page.pod.snapshot()["connected"] is False
    assert remote.scripts  # connect talked to the fake, disconnect did not need a new one
