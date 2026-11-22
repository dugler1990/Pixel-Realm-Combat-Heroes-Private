"""The outfit web page's server (tools/boss_sprite_pipeline/outfit_web.py): a fake driver stands in for outfit.py.
No paid call, no pod, no Blender."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tools.boss_sprite_pipeline import outfit_web as ow

FAKE = """import sys, time
args = sys.argv[1:]
print("=== fake", " ".join(args), flush=True)
time.sleep(float(__import__("os").environ.get("FAKE_SLEEP", "0.6")))
if "--accept" in args:
    print("STEP_DONE"); sys.exit(0)
print("STOPPED at front: front attempt 1 drawn: look at x.png"); sys.exit(2)
"""


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTFIT_DATA_ROOT", str(tmp_path))
    run = tmp_path / "generated" / "bosses" / "barb" / "outfits" / "naked"
    run.mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"character": "barb", "outfit": "naked", "steps": {
        "front": {"status": "done"}, "back": {"status": "gate"}}}), encoding="utf-8")
    (run / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    fake = tmp_path / "fake_driver.py"
    fake.write_text(FAKE, encoding="utf-8")
    jobs, pod = ow.Jobs(driver=[sys.executable, str(fake)]), ow.Pod()
    pod.host = pod.port = None
    srv = ow.make_server(0, jobs, pod)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base, run, jobs, pod
    srv.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait_idle(jobs, timeout=10):
    t0 = time.time()
    while any(jobs.lanes.values()) and time.time() - t0 < timeout:
        time.sleep(0.05)


def test_outfit_list_reads_run_json(server):
    base, *_ = server
    state = json.loads(get(base + "/api/state")[1])
    naked = next(o for o in state["outfits"] if o["outfit"] == "naked")
    assert {s["name"]: s["status"] for s in naked["steps"]}["back"] == "gate"
    assert naked["next"] == "back"
    assert set(state["keys"]) == {"openai", "leonardo", "hf"}


def test_one_command_per_lane_and_the_stop_message(server):
    base, _, jobs, _ = server
    code, r = post(base + "/api/do", {"character": "barb", "outfit": "naked", "action": "run", "step": "back"})
    assert code == 200, r
    code, r = post(base + "/api/do", {"character": "barb", "outfit": "loincloth", "action": "run", "step": "views"})
    assert code == 400 and "busy" in r["error"]
    wait_idle(jobs)
    state = json.loads(get(base + "/api/state")[1])
    last = state["jobs"]["done"][0]
    assert last["args"] == ["--only", "back"] and last["rc"] == 2
    assert last["stopped"].startswith("front: front attempt 1 drawn")


def test_buttons_become_driver_flags_only(server):
    base, _, jobs, _ = server
    o = {"character": "barb", "outfit": "naked"}
    bad = [{"action": "run", "step": "views"},                          # not a step of a body outfit
           {"action": "rm", "step": "back"},
           {"action": "retry", "step": "back", "retry": "please redraw"},  # must start with r / r1 / rb
           {"action": "retry", "step": "back", "retry": "r look @C:/Windows/win.ini"},
           {"action": "pick", "step": "trellis", "model": "front_left"},
           {"action": "run", "step": "trellis"}]                        # a pod step with no pod
    for b in bad:
        code, r = post(base + "/api/do", {**o, **b})
        assert code == 400, (b, r)
    code, r = post(base + "/api/do", {**o, "action": "accept", "step": "sides", "view": "front_left", "n": "3"})
    assert code == 200, r
    wait_idle(jobs)
    assert jobs.done[-1]["args"] == ["--only", "sides", "--view", "front_left", "--accept", "3"]


def test_pod_steps_get_the_pod_and_their_own_lane(server):
    base, _, jobs, pod = server
    pod.host, pod.port = "1.2.3.4", "2222"
    o = {"character": "barb", "outfit": "naked"}
    code, r = post(base + "/api/do", {**o, "action": "run", "step": "trellis"})
    assert code == 200, r
    code, r = post(base + "/api/do", {**o, "action": "run", "step": "skeleton"})
    assert code == 400 and "already" in r["error"]                       # same outfit: waits
    code, r = post(base + "/api/do", {"character": "barb", "outfit": "loincloth", "action": "run", "step": "cut"})
    assert code == 200, r                                               # local lane, another outfit: runs too
    wait_idle(jobs)
    pod_job = next(j for j in jobs.done if j["lane"] == "pod")
    assert pod_job["args"] == ["--only", "trellis", "--host", "1.2.3.4", "--port", "2222"]


def test_images_only_from_the_run_folders(server, tmp_path):
    base, run, *_ = server
    assert get(base + "/img?path=" + str(run / "pic.png"))[0] == 200
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/img?path=" + str(outside))
    assert e.value.code == 404


def test_models_choice_is_kept_in_run_json(server):
    base, run, jobs, _ = server
    code, r = post(base + "/api/do", {"character": "barb", "outfit": "naked", "action": "models",
                                      "models": ["front_back_sides", "eight_views", "bogus"]})
    assert code == 200, r
    wait_idle(jobs)
    assert jobs.done[-1]["args"] == ["--models", "front_back_sides,eight_views", "--status"]


# --- settings files made from the page ----------------------------------------------------------------------------

def test_a_new_character_and_outfit_from_the_page(server, tmp_path, monkeypatch):
    from tools.boss_sprite_pipeline import characters
    monkeypatch.setattr(characters, "OUTFITS", tmp_path / "outfits")
    base, *_ = server
    fields = json.loads(get(base + "/api/fields")[1])
    assert next(f for f in fields["fields"] if f["name"] == "rig_fit")["level"] == "character"
    code, r = post(base + "/api/character", {"character": "wizard", "data": {"rig_fit": "w.glb", "kind": "body"}})
    assert code == 400 and "kind belongs in an outfit file" in r["error"]
    char = {"_about": "test", "rig_fit": "generated/bosses/wizard/rig.glb", "roles": "r.json", "clips_blend": "c.blend",
            "clips_from": "barb", "roster": {"display_name": "Wizard"}}
    assert post(base + "/api/character", {"character": "wizard", "data": char})[0] == 200
    assert json.loads((tmp_path / "outfits" / "wizard" / "character.json").read_text(encoding="utf-8")) == char
    robe = {"kind": "body", "pack": "wizard_robe", "front": "f", "back": "b", "paint_look": "l.json"}
    code, r = post(base + "/api/outfit", {"character": "wizard", "outfit": "robe", "data": robe})
    assert code == 200 and any(m.startswith("no concept") for m in r["missing"])   # named, never filled in
    code, r = post(base + "/api/outfit", {"character": "wizard", "outfit": "robe",
                                          "data": {**robe, "images": {"front": "generated/none.png"}}})
    assert code == 400 and "images.front: no file" in r["error"]
    code, r = post(base + "/api/upload", {"character": "wizard", "input": True, "name": "front.png",
                                          "data": "data:image/png;base64,iVBORw0KGgo="})
    assert code == 200 and r["rel"].startswith("generated/bosses/wizard/inputs/") and Path(r["path"]).is_file()
    assert r["rel"] in json.loads(get(base + "/api/files?character=wizard&type=image")[1])["files"]
    code, r = post(base + "/api/outfit", {"character": "wizard", "outfit": "robe", "data": {**robe, "concept": r["rel"]}})
    assert code == 200, r
    saved = json.loads((tmp_path / "outfits" / "wizard" / "robe.json").read_text(encoding="utf-8"))
    assert saved["character"] == "wizard" and saved["concept"].endswith("front.png")
    state = json.loads(get(base + "/api/state")[1])
    row = next(o for o in state["outfits"] if o["outfit"] == "robe")
    assert row["kind"] == "body" and "error" not in row
    cfg = json.loads(get(base + "/api/config?character=wizard&outfit=robe")[1])
    assert cfg["characters"] == {"wizard": ["robe"]} and cfg["outfit"]["pack"] == "wizard_robe"


def test_names_and_broken_files(server, tmp_path, monkeypatch):
    from tools.boss_sprite_pipeline import characters
    monkeypatch.setattr(characters, "OUTFITS", tmp_path / "outfits")
    base, *_ = server
    for name in ("../x", "character", "a b"):
        assert post(base + "/api/character", {"character": name, "data": {}})[0] == 400, name
    assert post(base + "/api/outfit", {"character": "nobody", "outfit": "x", "data": {"kind": "body"}})[0] == 400
    (tmp_path / "outfits" / "w").mkdir(parents=True)
    (tmp_path / "outfits" / "w" / "character.json").write_text("{}", encoding="utf-8")
    (tmp_path / "outfits" / "w" / "hat.json").write_text('{"kind": "armour"}', encoding="utf-8")
    row = json.loads(get(base + "/api/state")[1])["outfits"][0]
    assert row["outfit"] == "hat" and "no character" in row["error"]       # listed with what is missing


def test_run_on_stays_in_its_lane(server):
    from tools.boss_sprite_pipeline import outfit as of
    _, _, _, pod = server
    ctx = of.Ctx("barb", "naked")                       # front done, back at its gate
    assert ow.build_args(ctx, {"action": "on"}, pod) == ("back", ["--to", "trellis"], "local")
    for s in ("back", "sides"):
        ctx.run["steps"][s] = {"status": "done"}
    with pytest.raises(ValueError, match="pod"):
        ow.build_args(ctx, {"action": "on"}, pod)
    pod.host, pod.port = "1.2.3.4", "22"
    assert ow.build_args(ctx, {"action": "on"}, pod) == ("trellis", ["--to", "skeleton", "--host", "1.2.3.4",
                                                                     "--port", "22"], "pod")


def test_use_an_image_for_a_view(server, tmp_path):
    base, run, jobs, _ = server
    o = {"character": "barb", "outfit": "naked"}
    code, r = post(base + "/api/do", {**o, "action": "use", "step": "front", "image": str(run / "pic.png")})
    assert code == 200, r
    wait_idle(jobs)
    assert jobs.done[-1]["args"] == ["--only", "front", "--use", str(run / "pic.png")]
    outside = tmp_path / "x.png"
    outside.write_bytes(b"x")
    for b in ({"step": "front", "image": str(outside)}, {"step": "trellis", "image": str(run / "pic.png")}):
        assert post(base + "/api/do", {**o, "action": "use", **b})[0] == 400, b
