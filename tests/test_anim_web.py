"""The animation page. A fake map stands in for Blender. No pod, no bpy."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from tools.boss_sprite_pipeline import anim_web as aw
from tools.boss_sprite_pipeline.rigging.map import character as C
from tools.boss_sprite_pipeline.rigging.rig import version as V

from test_rigging import _tiny_glb

BVH = "HIERARCHY\nROOT Hips\n{\n  OFFSET 0 100 0\n  CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation\n  JOINT Head\n  {\n    OFFSET 0 20 0\n    CHANNELS 3 Zrotation Yrotation Xrotation\n  }\n}\nMOTION\nFrames: 0\n"


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIM_DATA_ROOT", str(tmp_path))
    bosses = tmp_path / "generated" / "bosses"
    lib = bosses / "anim_library"
    lib.mkdir(parents=True)
    (bosses / "clips").mkdir()
    (bosses / "clips" / "walk_v1_00.bvh").write_text(BVH, encoding="utf-8")
    (lib / "index.json").write_text(json.dumps([
        {"id": "walk_v1_00", "bvh": "bosses/clips/walk_v1_00.bvh", "source": "soma", "prompt": None,
         "model": None, "duration": None, "maps": {}}
    ]), encoding="utf-8")
    glb = _tiny_glb(bosses / "barb" / "rig.glb", ["bone_0", "bone_5"])
    V.import_v1("barb", str(glb), {"root": "bone_0", "head": "bone_5"}, "test")
    C.create("barb", "human", rig=1)
    aw.JOBS = aw.Jobs()
    srv = aw.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base, lib
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


def wait_idle(timeout=5):
    import time
    t0 = time.time()
    while any(aw.JOBS.lanes.values()) and time.time() - t0 < timeout:
        time.sleep(0.02)


def test_state_lists_characters_from_their_files_with_versions_and_schema(server):
    base, _ = server
    state = json.loads(get(base + "/api/state")[1])
    barb = state["characters"][0]
    assert barb["id"] == "barb" and barb["rig"] == 1 and barb["template"] == "human"
    assert barb["versions"][0]["step"] == "import" and barb["versions"][0]["accepted"]
    assert barb["settings"]["mode"] == {"value": "ik", "from": "character"}
    assert {s["name"] for s in state["schema"]} >= {"mode", "bind", "arm_cap", "jaw_closed"}


def test_list_and_bvh_and_the_path_jail(server, tmp_path):
    base, _ = server
    assert get(base + "/bvh?id=walk_v1_00")[0] == 200
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/glb?path=../secret.glb")
    assert e.value.code == 404
    outside = tmp_path / "secret.glb"
    outside.write_bytes(b"x")
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/glb?path=" + str(outside))
    assert e.value.code == 404


def test_one_map_at_a_time_and_the_index_records_the_rig_version(server, monkeypatch):
    base, lib = server
    import time

    def fake(clip_id, character_id, lines):
        time.sleep(0.4)
        return {"glb": f"characters/barb/view/v1/clips/{clip_id}.glb", "rig": 1, "bone_hash": "h", "bake": "x"}

    monkeypatch.setattr(aw, "run_map", fake)
    code, r = post(base + "/api/map", {"clip": "walk_v1_00", "character": "barb"})
    assert code == 200, r
    code, r = post(base + "/api/map", {"clip": "walk_v1_00", "character": "barb"})
    assert code == 400 and "busy" in r["error"]
    wait_idle()
    index = json.loads((lib / "index.json").read_text(encoding="utf-8"))
    assert index[0]["maps"]["barb"]["rig"] == 1


def test_panel_edits_are_decisions_in_the_character_file(server, monkeypatch):
    base, _ = server
    monkeypatch.setattr(aw, "run_map", lambda c, k, lines: {"glb": "x", "rig": 1, "bone_hash": "h", "bake": "x"})
    code, r = post(base + "/api/character", {"character": "barb",
                                            "patch": {"arm_cap": 80, "bind": {"neck": True, "root": None}}})
    assert code == 200, r
    m = C.load("barb")["map"]
    assert m["arm_cap"] == 80 and m["bind"] == {"neck": True}
    code, r = post(base + "/api/character", {"character": "barb", "patch": {"arm_cap": 500}})
    assert code == 400
    code, r = post(base + "/api/character", {"character": "barb", "patch": {"barrel": 1}})
    assert code == 400 and "unknown" in r["error"]
    code, r = post(base + "/api/character", {"character": "barb", "patch": {}, "clip": "walk_v1_00"})
    assert code == 200 and r["rebake"]
    wait_idle()


def test_bake_report_flags_a_stale_bake(server, tmp_path):
    base, _ = server
    run = aw.bake_dir("barb", "walk_v1_00") / "run.json"
    run.parent.mkdir(parents=True)
    run.write_text(json.dumps({"rig": {"version": 1, "bone_hash": "old"}, "clips": {"walk_v1_00": {
        "pose_check": {"worst": None}, "proportions": {}}}}), encoding="utf-8")
    r = json.loads(get(base + "/api/bake?clip=walk_v1_00&character=barb")[1])
    assert r["baked"] and r["stale"] and not r["older_rig"]


def test_prompt_needs_a_pod_and_a_finished_cell_joins_the_list(server, monkeypatch):
    base, lib = server
    code, r = post(base + "/api/prompt", {"name": "haymaker", "prompt": "A person swings."})
    assert code == 400 and "pod" in r["error"]

    def fake(cell_path, dest_dir, host, port):
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "haymaker_00.bvh").write_text(BVH, encoding="utf-8")

    monkeypatch.setattr(aw, "execute_prompt", fake)
    code, r = post(base + "/api/prompt", {"name": "haymaker", "prompt": "A person swings.",
                                         "host": "1.2.3.4", "port": "22"})
    assert code == 200, r
    wait_idle()
    index = json.loads((lib / "index.json").read_text(encoding="utf-8"))
    row = next(c for c in index if c["id"] == "haymaker")
    assert row["model"] == "Kimodo-SOMA-RP-v1" and row["source"] == "soma"


def test_stop_kills_the_running_process_and_marks_the_job_stopped(server, monkeypatch):
    import sys
    import time
    base, _ = server

    def slow(clip_id, character_id, lines):
        aw._run([sys.executable, "-c", "import time\nfor i in range(60):\n print(i, flush=True); time.sleep(0.5)"], lines)

    monkeypatch.setattr(aw, "run_map", slow)
    assert post(base + "/api/map", {"clip": "walk_v1_00", "character": "barb"})[0] == 200
    for _ in range(50):                               # wait until the child is running and printing
        job = aw.JOBS.lanes["local"]
        if job and job.get("proc") and job["lines"][-1:] != [] and job["lines"][-1].strip().isdigit():
            break
        time.sleep(0.1)
    t0 = time.time()
    code, r = post(base + "/api/stop", {})
    assert code == 200 and r["stopped"]
    wait_idle()
    assert time.time() - t0 < 5
    done = aw.JOBS.done[-1]
    assert done["rc"] == 2 and "STOPPED" in done["lines"][-1]


def test_match_reads_the_rig_version_roles(server):
    base, _ = server
    status, body = get(base + "/api/match?clip=walk_v1_00&character=barb")
    assert status == 200
    report = json.loads(body)
    assert set(report["roles"]) == {"root", "head"} and report["rig"] == 1
