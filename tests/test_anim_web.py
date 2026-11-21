"""The animation page. A fake map stands in for Blender. No pod, no bpy."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tools.boss_sprite_pipeline import anim_web as aw

BVH = "HIERARCHY\nROOT Hips\n{\n  OFFSET 0 100 0\n  CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation\n  JOINT Head\n  {\n    OFFSET 0 20 0\n    CHANNELS 3 Zrotation Yrotation Xrotation\n  }\n}\nMOTION\nFrames: 0\n"
ROLES = {
    "root": "bone_0", "spine": "bone_1", "spine2": "bone_2", "chest": "bone_3",
    "neck": "bone_4", "head": "bone_5",
    "arm_l": {"shoulder": "b6", "elbow": "b7", "wrist": "b8", "hand": "b9"},
    "arm_r": {"shoulder": "b13", "elbow": "b14", "wrist": "b15", "hand": "b16"},
    "leg_l": {"hip": "b20", "knee": "b21", "ankle": "b22", "foot": "b23"},
    "leg_r": {"hip": "b24", "knee": "b25", "ankle": "b26", "foot": "b27"},
}


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIM_DATA_ROOT", str(tmp_path))
    bosses = tmp_path / "generated" / "bosses"
    lib = bosses / "anim_library"
    lib.mkdir(parents=True)
    (bosses / "clips").mkdir()
    (bosses / "clips" / "walk_v1_00.bvh").write_text(BVH, encoding="utf-8")
    (bosses / "barb_roles.json").write_text(json.dumps(ROLES), encoding="utf-8")
    (lib / "index.json").write_text(json.dumps([
        {"id": "walk_v1_00", "bvh": "bosses/clips/walk_v1_00.bvh", "prompt": None,
         "model": None, "duration": None, "maps": {}}
    ]), encoding="utf-8")
    (lib / "characters.json").write_text(json.dumps([
        {"id": "barb", "recipe": "human", "target": "barb", "source": "soma",
         "roles": "bosses/barb_roles.json", "base": None, "view": "bosses/barb/viewer/anim_suite"}
    ]), encoding="utf-8")
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


def test_list_and_bvh_and_the_path_jail(server, tmp_path):
    base, _ = server
    state = json.loads(get(base + "/api/state")[1])
    assert state["clips"][0]["id"] == "walk_v1_00"
    assert get(base + "/bvh?id=walk_v1_00")[0] == 200
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/glb?path=../secret.glb")
    assert e.value.code == 404
    outside = tmp_path / "secret.glb"
    outside.write_bytes(b"x")
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + "/glb?path=" + str(outside))
    assert e.value.code == 404


def test_one_map_at_a_time_and_the_index_records_it(server, monkeypatch):
    base, lib = server
    import time

    def fake(clip_id, character_id, lines):
        lines.append("mapping " + clip_id)
        time.sleep(0.4)
        return f"bosses/barb/viewer/anim_suite/clips/{clip_id}.glb"

    monkeypatch.setattr(aw, "run_map", fake)
    code, r = post(base + "/api/map", {"clip": "walk_v1_00", "character": "barb"})
    assert code == 200, r
    code, r = post(base + "/api/map", {"clip": "walk_v1_00", "character": "barb"})
    assert code == 400 and "busy" in r["error"]
    wait_idle()
    index = json.loads((lib / "index.json").read_text(encoding="utf-8"))
    assert index[0]["maps"]["barb"].endswith("walk_v1_00.glb")
    assert aw.JOBS.done[-1]["rc"] == 0


def test_fit_patch_is_what_the_rebake_will_read(server, monkeypatch):
    base, lib = server
    monkeypatch.setattr(aw, "run_map", lambda c, k, lines: "bosses/barb/viewer/anim_suite/clips/walk_v1_00.glb")
    code, r = post(base + "/api/fit", {"character": "barb", "clip": "walk_v1_00",
                                      "patch": {"barrel_chest": 1, "arm_cap": 90, "bind_match": False,
                                                "nope": 5}})
    assert code == 200, r
    saved = json.loads((lib / "fits" / "barb.json").read_text(encoding="utf-8"))
    assert saved == {"barrel_chest": 1, "arm_cap": 90, "bind_match": False}
    wait_idle()
    from tools.boss_sprite_pipeline.rigmap.fit import knob_env
    assert knob_env(saved)["CLAVICLE_DAMP"] == "0.0000"


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
    assert row["model"] == "Kimodo-SOMA-RP-v1"
    assert row["bvh"].endswith("haymaker.bvh")
    assert (lib / "bvh" / "haymaker.bvh").is_file()


def test_match_on_the_fixture_reports_a_human_pair_count(server):
    base, _ = server
    # The fixture BVH only has Hips and Head, so the pair set is the overlap, not 22.
    status, body = get(base + "/api/match?clip=walk_v1_00&character=barb")
    assert status == 200
    report = json.loads(body)
    assert "head" in report["roles"]
    assert report["recipe"] == "human"
