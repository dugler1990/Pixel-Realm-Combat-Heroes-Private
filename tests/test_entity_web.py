"""The entity web page's server. A fake driver stands in for the CLI. No paid call, no game."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

import pytest

from tools.entity_pipeline import cli
from tools.entity_pipeline import web
from tools.review_web import Jobs

FAKE = """import sys, time
print(" ".join(sys.argv[1:]), flush=True)
time.sleep(0.6)
"""


def patch_roots(monkeypatch, tmp_path):
    work = (tmp_path / "work").resolve()
    monsters = (tmp_path / "monsters").resolve()
    maps = (tmp_path / "maps").resolve()
    work.mkdir()
    monsters.mkdir()
    maps.mkdir()
    monkeypatch.setattr(web, "WORK", work)
    monkeypatch.setattr(web, "MONSTERS", monsters)
    monkeypatch.setattr(web, "MEDIA_ROOTS", [work, monsters])
    monkeypatch.setattr(web, "MAP_ROOTS", [work, maps])
    return work, monsters, maps


@pytest.fixture()
def server(tmp_path, monkeypatch):
    work, monsters, maps = patch_roots(monkeypatch, tmp_path)
    fake = tmp_path / "fake_driver.py"
    fake.write_text(FAKE, encoding="utf-8")
    jobs = Jobs([sys.executable, str(fake)], tmp_path)
    srv = web.make_server(0, jobs)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield {"base": base, "work": work, "monsters": monsters, "maps": maps, "jobs": jobs}
    srv.shutdown()


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def wait_idle(jobs, timeout=10):
    t0 = time.time()
    while jobs.running and time.time() - t0 < timeout:
        time.sleep(0.05)


def _session(work, maps):
    folder = work / "s"
    (folder / "cells").mkdir(parents=True)
    (folder / "cells" / "s_a.png").write_bytes(b"\x89PNG")
    (folder / "uploads").mkdir()
    attach = folder / "uploads" / "ref.png"
    attach.write_bytes(b"\x89PNG")
    image = maps / "map.png"
    image.write_bytes(b"\x89PNG")
    return folder, image, attach


def test_every_command_parses(tmp_path, monkeypatch):
    work, _monsters, maps = patch_roots(monkeypatch, tmp_path)
    _folder, image, attach = _session(work, maps)
    rows = {
        "scene": ({"map": str(image), "force": True, "why": "too dark", "attach": str(attach)}, cli.cmd_scene),
        "sheet": ({"force": True, "why": "flat", "attach": str(attach)}, cli.cmd_sheet),
        "cut": ({}, cli.cmd_cut),
        "stats": ({"force": True}, cli.cmd_stats),
        "anim": ({"name": "s_a", "action": "move", "force": True, "why": "slow"}, cli.cmd_anim),
        "anim-all": ({}, cli.cmd_anim_all),
        "frames": ({"name": "s_a", "band": "center"}, cli.cmd_frames),
        "brawl": ({"each": 2, "hold": 30}, cli.cmd_brawl),
    }
    for step, (extra, func) in rows.items():
        key, args, locks = web.build_argv({"step": step, "session": "s", **extra})
        parsed = cli.build_parser().parse_args(args)
        assert key == "s"
        assert parsed.func is func
        assert ("--yes" in args) is (step != "stats")
        if step == "brawl":
            assert locks == {"session:s", "game"}
            assert parsed.each == 2 and parsed.hold == 30
        else:
            assert locks == {"session:s"}
        if step == "anim":
            assert parsed.action == "move" and parsed.why == "slow" and parsed.force
        if step == "frames":
            assert parsed.band == "center" and parsed.name == "s_a"
        if step == "scene":
            assert parsed.why == "too dark" and parsed.force and Path(parsed.attach).name == "ref.png"


def test_bad_commands_are_400(server):
    ctx = server
    _session(ctx["work"], ctx["maps"])
    outside = ctx["work"].parent / "outside.png"
    outside.write_bytes(b"\x89PNG")
    bad = [
        {"step": "nope", "session": "s"},
        {"step": "cut", "session": "a/b"},
        {"step": "anim", "session": "s", "name": "s_a", "why": "x"},
        {"step": "scene", "session": "s", "map": str(outside)},
        {"step": "brawl", "session": "s", "each": 0, "hold": 60},
        {"step": "brawl", "session": "s", "each": 1, "hold": 0},
    ]
    for body in bad:
        code, reply = post(ctx["base"] + "/api/do", body)
        assert code == 400, (body, reply)


def test_locks_keep_one_command_per_session_and_one_game(server):
    ctx = server
    base = ctx["base"]
    code, reply = post(base + "/api/do", {"step": "cut", "session": "s"})
    assert code == 200, reply
    code, reply = post(base + "/api/do", {"step": "sheet", "session": "s"})
    assert code == 400 and "busy" in reply["error"]
    code, reply = post(base + "/api/do", {"step": "cut", "session": "t"})
    assert code == 200, reply
    wait_idle(ctx["jobs"])
    code, reply = post(base + "/api/do", {"step": "brawl", "session": "s", "each": 1, "hold": 1})
    assert code == 200, reply
    code, reply = post(base + "/api/do", {"step": "brawl", "session": "t", "each": 1, "hold": 1})
    assert code == 400 and "game" in reply["error"]


def test_media_stays_inside_and_honours_a_range(server):
    ctx = server
    png = ctx["work"] / "pic.png"
    png.write_bytes(b"\x89PNG")
    text = ctx["work"] / "note.txt"
    text.write_bytes(b"secret")
    video = ctx["work"] / "clip.mp4"
    video.write_bytes(b"0123456789")
    outside = ctx["work"].parent / "secret.png"
    outside.write_bytes(b"nope")
    assert fetch(ctx["base"] + "/media?path=" + quote(str(outside)))[0] == 404
    assert fetch(ctx["base"] + "/media?path=" + quote(str(text)))[0] == 404
    assert fetch(ctx["base"] + "/media?path=" + quote(str(png)))[0] == 200
    code, data, headers = fetch(
        ctx["base"] + "/media?path=" + quote(str(video)), headers={"Range": "bytes=0-3"})
    assert code == 206
    assert data == b"0123"
    assert headers["Content-Range"] == "bytes 0-3/10"


def test_state_reports_keys_set_or_not_and_never_the_value(server, monkeypatch):
    sentinel = "sk-" + ("x" * 24)
    monkeypatch.delenv("LEONARDO_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", sentinel)
    code, raw, _headers = fetch(server["base"] + "/api/state")
    assert code == 200
    text = raw.decode("utf-8")
    assert sentinel not in text
    assert os.environ["OPENAI_API_KEY"] not in text
    body = json.loads(raw)
    assert body["keys"] == {"openai": True, "leonardo": False}


def test_status_follows_inputs(server):
    ctx = server
    w = ctx["work"] / "s"
    w.mkdir()
    (w / "scene.png").write_bytes(b"\x89PNG")
    sheet = w / "sheet.png"
    layout = w / "layout.json"
    sheet.write_bytes(b"\x89PNG")
    layout.write_text("{}", encoding="utf-8")
    (w / "cells").mkdir()
    (w / "cells" / "s_a.png").write_bytes(b"\x89PNG")
    old, new = 1_700_000_000, 1_700_000_100
    os.utime(sheet, (old, old))
    os.utime(layout, (new, new))

    def detail():
        code, raw, _headers = fetch(ctx["base"] + "/api/session?name=s")
        assert code == 200
        return json.loads(raw)

    assert detail()["steps"]["cut"] == "done"
    os.utime(sheet, (new + 50, new + 50))
    body = detail()
    assert body["steps"]["cut"] == "stale"
    assert body["steps"]["anim"] == "missing"
    clip = w / "anim" / "s_a" / "idle.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"clip")
    os.utime(w / "cells" / "s_a.png", (old, old))
    os.utime(clip, (new, new))
    assert detail()["steps"]["anim"] == "partial"


def test_log_shows_the_running_command(server):
    ctx = server
    code, reply = post(ctx["base"] + "/api/do", {"step": "cut", "session": "s"})
    assert code == 200, reply
    seen = ""
    t0 = time.time()
    while time.time() - t0 < 5:
        _code, raw, _headers = fetch(ctx["base"] + "/api/log?name=s")
        body = json.loads(raw)
        seen = "\n".join(body.get("lines") or [])
        if "cut" in seen and "--session" in seen:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(seen)
    wait_idle(ctx["jobs"])


def test_unknown_session_is_404_and_creates_nothing(server):
    code, raw, _headers = fetch(server["base"] + "/api/session?name=nope")
    assert code == 404
    assert not (server["work"] / "nope").exists()
