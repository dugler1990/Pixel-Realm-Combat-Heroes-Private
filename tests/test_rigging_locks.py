"""Locked reference bakes: the pure transfer on saved fixtures must give the recorded angles (±0.1 deg).

Fixtures: tests/fixtures/rig_*.npz (make_rig_fixture.py). Locks: tests/fixtures/rig_locks/*.json,
recorded 2026-11-21. The barb locks equal the pre-split bake on every bone; the chest row changed when
the pose check started measuring chest -> neck instead of whichever child came first (old_bones).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tools.boss_sprite_pipeline.rigging import sources
from tools.boss_sprite_pipeline.rigging.map import character as C
from tools.boss_sprite_pipeline.rigging.map import templates
from tools.boss_sprite_pipeline.rigging.map.match import match
from tools.boss_sprite_pipeline.rigging.map.transfer import transfer

FIX = Path(__file__).parent / "fixtures"
TOL = 0.1


def _load(name):
    z = np.load(FIX / f"rig_{name}.npz")
    meta = json.loads(str(z["meta"]))
    joints, frames = meta["joints"], meta["frames"]
    world = {f: {j: z["world"][i, k] for k, j in enumerate(joints)} for i, f in enumerate(frames)}
    src = {"frames": frames, "world": world, "rest_world": {j: z["rest"][k] for k, j in enumerate(joints)},
           "parent": meta["src_parent"], "height_f0": meta["height_f0"]}
    rig = {"tw": z["tw"], "rest_arm": {b: z["rest_arm"][i] for i, b in enumerate(meta["rig_order"])},
           "parent": meta["rig_parent"], "length": meta["rig_length"], "height": meta["rig_height"],
           "order": meta["rig_order"]}
    return src, rig, meta["roles"]


def _bake(name, cid, mp):
    src, rig, roles = _load(name)
    m = match(sources.label(list(src["world"][src["frames"][0]]), "soma"), roles, rig["order"],
              static=sources.soma.STATIC)
    depth = lambda b: 0 if not rig["parent"].get(b) else 1 + depth(rig["parent"][b])
    use = sorted([(p["role"], p["source"], p["target"]) for p in m["paired"]], key=lambda u: depth(u[2]))
    s = C.resolve({"id": cid, "map": mp}, "soma")
    vals = {k: v["value"] for k, v in s.items()}
    vals["flags"] = C.bind_flags(s, [u[0] for u in use])
    return transfer(src, rig, roles, use, vals), len(use)


def _lock(name):
    return json.loads((FIX / "rig_locks" / f"{name}.json").read_text(encoding="utf-8"))


def _same(got, lock):
    for role, deg in lock["by_role"].items():
        assert abs(got["pose_check"]["by_role"][role] - deg) <= TOL, (role, got["pose_check"]["by_role"][role], deg)


HUMAN = templates.get("human")["map"]


@pytest.mark.parametrize("lock,mp", [
    ("barb_human", HUMAN),
    ("barb_bindhips", dict(HUMAN, mode="rot", bind={"neck": False})),
    ("barb_bindoff", dict(HUMAN, mode="rot", bind_default=False, bind={})),
    ("barb_neckbound", dict(HUMAN, bind={"root": False})),
])
def test_barb_locks(lock, mp):
    got, n = _bake("barb_hit", "barb", mp)
    assert n == 22
    _same(got, _lock(lock))


def test_known_failures_stay_failures():
    hips, _ = _bake("barb_hit", "barb", dict(HUMAN, mode="rot", bind={"neck": False}))
    assert hips["pose_check"]["worst"]["bone"] == "Hips>bone_0" and hips["pose_check"]["worst"]["deg"] == 149.3
    off, _ = _bake("barb_hit", "barb", dict(HUMAN, mode="rot", bind_default=False, bind={}))
    assert off["pose_check"]["worst"]["bone"] == "RightForeArm>bone_15"


def test_human_template_passes_and_binding_the_neck_reaches_the_bake():
    skip, _ = _bake("barb_hit", "barb", HUMAN)
    bound, _ = _bake("barb_hit", "barb", dict(HUMAN, bind={"root": False}))
    assert skip["pose_check"]["worst"]["deg"] == 29.4 and not skip["pose_check"]["fail"]
    assert abs(skip["pose_check"]["by_role"]["neck"] - bound["pose_check"]["by_role"]["neck"]) > 10


def test_demon_lock():
    got, n = _bake("demon_walk", "demon", templates.get("demon")["map"])
    assert n == 20
    _same(got, _lock("demon_walk"))


def test_transfer_without_a_setting_raises():
    src, rig, roles = _load("barb_hit")
    with pytest.raises(ValueError):
        transfer(src, rig, roles, [], {"mode": "ik"})


def test_human_template_is_the_graded_ik2_bake():
    run = Path(r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\barb\anim_test\retarget_ik2\run.json")
    if not run.is_file():
        pytest.skip("Boss tree not beside this one")
    r = json.loads(run.read_text(encoding="utf-8"))
    assert (r["mode"], r["IK_BODY"], r["BIND_MATCH"], r["ARM_ELEV_CAP"], r["CLAVICLE_DAMP"], r["ROOT_LOC"]) == \
        (HUMAN["mode"], HUMAN["ik_body"], HUMAN["bind_default"], HUMAN["arm_cap"], HUMAN["clavicle_damp"],
         HUMAN["root_loc"])
    assert r["BIND_SKIP"] == ["bone_0", "bone_4"] and HUMAN["bind"] == {"root": False, "neck": False}
    assert r["settings_from"]["bind_ref"]["value"] == HUMAN["reference_pose"]
