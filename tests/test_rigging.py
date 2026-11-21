"""rigging: roles, sources, match, settings, character file, rig versions, proportions. No Blender."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.boss_sprite_pipeline.rigging import roles as R
from tools.boss_sprite_pipeline.rigging import sources
from tools.boss_sprite_pipeline.rigging.map import character as C
from tools.boss_sprite_pipeline.rigging.map import pose_check as PC
from tools.boss_sprite_pipeline.rigging.map import proportions, templates
from tools.boss_sprite_pipeline.rigging.map.match import match
from tools.boss_sprite_pipeline.rigging.settings import Setting, SettingError, resolve

BOSS = Path(r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated")
SOMA_NAMES = list(sources.soma.JOINTS) + ["Root", "LeftHandThumb1"]

DEMON = {
    "root": "bone_0", "spine": "bone_1", "chest": "bone_12", "neck": "bone_13", "head": "bone_34",
    "jaw": "jaw", "tail": ["bone_35"],
    "arm_l": {"shoulder": "bone_14", "elbow": "bone_15", "wrist": "bone_16", "hand": "bone_17",
              "fingers": ["bone_18"]},
    "arm_r": {"shoulder": "bone_24", "elbow": "bone_25", "wrist": "bone_26", "hand": "bone_27"},
    "leg_l": {"hip": "bone_2", "knee": "bone_3", "ankle": "bone_4", "foot": "bone_5", "toe": "bone_6"},
    "leg_r": {"hip": "bone_7", "knee": "bone_8", "ankle": "bone_9", "foot": "bone_10"},
    "wing_l": {"arm": "wing_L_a", "fan": "wing_L_b"},
}
BARB = {
    "root": "bone_0", "spine": "bone_1", "spine2": "bone_2", "chest": "bone_3", "neck": "bone_4", "head": "bone_5",
    "arm_l": {"shoulder": "bone_6", "elbow": "bone_7", "wrist": "bone_8", "hand": "bone_9"},
    "arm_r": {"shoulder": "bone_13", "elbow": "bone_14", "wrist": "bone_15", "hand": "bone_16"},
    "leg_l": {"hip": "bone_20", "knee": "bone_21", "ankle": "bone_22", "foot": "bone_23"},
    "leg_r": {"hip": "bone_24", "knee": "bone_25", "ankle": "bone_26", "foot": "bone_27"},
}
DEMON_20 = {"root", "spine", "chest", "head"} | {p + s for p in R.LIMB for s in R.SIDES}
HUMAN_22 = DEMON_20 | {"spine2", "neck"}


def test_canonical_translates_the_off_by_one_keys_once():
    b = R.canonical(BARB, "anun")
    assert b["upper_arm.L"] == "bone_7" and b["forearm.L"] == "bone_8" and b["clavicle.L"] == "bone_6"
    assert b["thigh.R"] == "bone_24" and b["neck"] == "bone_4" and b["head"] == "bone_5"
    d = R.canonical(DEMON, "demon_hand")
    assert d["head"] == "bone_13" and d["snout"] == "bone_34" and "neck" not in d
    assert d["jaw"] == "jaw" and d["wing.L"] == "wing_L_a" and d["toe.L"] == "bone_6" and d["tail.1"] == "bone_35"
    with pytest.raises(ValueError):
        R.canonical(BARB, "guess")


def test_pairs_are_the_locked_sets_and_static_joints_are_not_driven():
    src = sources.label(SOMA_NAMES, "soma")
    assert src["LeftEye"] == "eye.L" and src["Jaw"] == "jaw" and "Root" not in src
    barb = match(src, R.canonical(BARB, "anun"), static=sources.soma.STATIC)
    assert set(barb["roles"]) == HUMAN_22
    assert {"eye.L", "eye.R", "jaw"} <= set(barb["missing_required"])
    assert "neck2" in barb["missing"] and "neck2" not in barb["missing_required"]
    demon = match(src, R.canonical(DEMON, "demon_hand"), static=sources.soma.STATIC)
    assert set(demon["roles"]) == DEMON_20
    assert next(p for p in demon["paired"] if p["role"] == "head")["target"] == "bone_13"
    assert demon["static"] == ["jaw"]            # he has a jaw, Kimodo's never moves


def test_settings_resolve_records_sources_and_refuses_gaps_and_typos():
    decls = [Setting("a", "float", "x", min=0, max=1), Setting("b", "bool", "y", default=True)]
    got = resolve(decls, [("template", {"a": 0.5}), ("panel", {"a": "0.25"})])
    assert got["a"] == {"value": 0.25, "from": "panel"} and got["b"] == {"value": True, "from": "default"}
    with pytest.raises(SettingError):
        resolve(decls, [("template", {})])
    with pytest.raises(SettingError):
        resolve(decls, [("template", {"a": 2})])
    with pytest.raises(SettingError):
        resolve(decls, [("template", {"a": 0.1, "typo": 1})])


def test_templates_are_complete_and_copied(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIM_DATA_ROOT", str(tmp_path))
    for name in templates.TEMPLATES:
        C.validate({"id": "x", "template": name, "rig": 1, "map": templates.get(name)["map"]})
    char = C.create("barb", "human", rig=1)
    templates.TEMPLATES["human"]["map"]["arm_cap"] = 10.0     # a later template edit...
    try:
        assert C.load("barb")["map"]["arm_cap"] == 90.0     # ...does not reach the character
    finally:
        templates.TEMPLATES["human"]["map"]["arm_cap"] = 90.0
    assert char["map"]["bind"] == {"root": False, "neck": False}


def test_bind_flags_and_the_g1_demon_pair(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIM_DATA_ROOT", str(tmp_path))
    demon = {"id": "demon", "template": "demon", "rig": 1, "map": templates.get("demon")["map"]}
    s = C.resolve(demon, "g1")
    flags = C.bind_flags(s, ["ankle.L", "thigh.L"])
    assert flags == {"ankle.L": False, "thigh.L": False}
    human = {"id": "barb", "template": "human", "rig": 1, "map": templates.get("human")["map"]}
    f = C.bind_flags(C.resolve(human, "soma"), ["root", "neck", "head", "forearm.L"])
    assert f == {"root": False, "neck": False, "head": True, "forearm.L": True}
    C.create("barb", "human", rig=1)
    C.set_map("barb", {"bind": {"neck": True, "root": None}, "arm_cap": 80})
    m = C.load("barb")["map"]
    assert m["bind"] == {"neck": True} and m["arm_cap"] == 80
    with pytest.raises(SettingError):
        C.set_map("barb", {"arm_cap": 500})


def test_proportions_compare_lengths_over_height():
    src = {"root": (0, 0, 1), "head": (0, 0, 2), "foot.L": (0, 0, 0),
           "clavicle.L": (-0.1, 0, 1.6), "clavicle.R": (0.1, 0, 1.6),
           "upper_arm.L": (-0.2, 0, 1.6), "forearm.L": (-0.5, 0, 1.6), "hand.L": (-0.8, 0, 1.6)}
    tgt = {k: (x * 2, y, z) for k, (x, y, z) in src.items()}     # twice as wide, same height
    p = proportions.measure(src, tgt)
    assert p["shoulder_ratio"] == 2.0 and p["arm_ratio"] == 2.0


def test_segment_runs_along_the_chain_not_table_order():
    use = [("chest", "Chest", "c"), ("clavicle.L", "LeftShoulder", "cl"), ("neck", "Neck1", "n")]
    tpar = {"c": None, "cl": "c", "n": "c"}
    spar = {"Chest": None, "LeftShoulder": "Chest", "Neck1": "Chest"}
    segs = PC.segments(use, spar, tpar)
    assert ("chest", "Chest", "c", "Neck1", "n") in segs


def test_rig_versions_number_link_and_gate(tmp_path, monkeypatch):
    from tools.boss_sprite_pipeline.rigging.rig import version as V
    monkeypatch.setenv("ANIM_DATA_ROOT", str(tmp_path))
    glb = _tiny_glb(tmp_path / "a.glb", ["bone_0", "bone_1"])
    v1 = V.import_v1("x", str(glb), {"root": "bone_0", "spine": "bone_1"}, "history text")
    assert v1["version"] == 1 and v1["accepted"] and v1["input"] is None
    n, d = V.begin("x")
    assert n == 2
    _tiny_glb(d / "rig.glb", ["bone_0", "bone_1", "jaw"])
    V.finish("x", n, step="add_bone", kind="bone_set", settings={}, input_n=1,
             roles={"root": "bone_0", "jaw": "jaw"}, checks={"pose_sheet": {"gate": True, "pass": False}})
    assert [r["version"] for r in V.chain("x", 2)] == [2, 1]
    assert V.load("x", 2)["bone_hash"] != v1["bone_hash"]
    with pytest.raises(ValueError):
        V.accept("x", 2)
    n3, _ = V.begin("x")
    assert n3 == 3                                # 2 is taken even before it is accepted
    with pytest.raises(ValueError):               # roles must name real bones
        V.finish("x", n3, step="m", kind="weights", settings={}, input_n=2, roles={"root": "nope"}, glb=glb)


def test_a_step_makes_an_unaccepted_version_with_evaluated_checks(tmp_path, monkeypatch):
    import types
    from tools.boss_sprite_pipeline.rigging.rig import run_step as RS
    from tools.boss_sprite_pipeline.rigging.rig import steps as S
    from tools.boss_sprite_pipeline.rigging.rig import version as V
    monkeypatch.setenv("ANIM_DATA_ROOT", str(tmp_path))
    glb = _tiny_glb(tmp_path / "a.glb", ["bone_0", "bone_1"])
    V.import_v1("x", str(glb), {"root": "bone_0"}, "h")

    def run(ctx):
        out = _tiny_glb(ctx.dir / "rig.glb", ["bone_0", "bone_1"])
        ctx.check("weights", {"unweighted_verts": ctx.settings["bad"]})
        return {"glb": out, "roles": ctx.input_roles}

    fake = types.SimpleNamespace(NAME="fake", KIND="auto", LANE="local", DOC="",
                                 SETTINGS=[Setting("bad", "int", "x", default=0)],
                                 CHECKS={"weights": [("unweighted_verts", "==", 0, True)]}, run=run)
    monkeypatch.setitem(S.STEPS, "fake", fake)
    rec = RS.run_step("x", "fake", {"bad": 3}, 1, [])
    assert rec["version"] == 2 and rec["kind"] == "weights" and not rec["accepted"]
    assert rec["checks"]["weights"]["pass"] is False
    with pytest.raises(ValueError):
        V.set_current("x", 2)                      # a failed gate cannot become the rig

    def boom(ctx):
        raise RuntimeError("blender died")
    monkeypatch.setitem(S.STEPS, "fake", types.SimpleNamespace(**{**fake.__dict__, "run": boom}))
    with pytest.raises(RuntimeError):
        RS.run_step("x", "fake", {}, 1, [])
    assert V.versions("x") == [1, 2]               # the failed step left no half version


def _tiny_glb(path: Path, bones: list[str]) -> Path:
    import struct
    nodes = [{"name": b} for b in bones]
    for i in range(len(nodes) - 1):
        nodes[i]["children"] = [i + 1]
    g = {"asset": {"version": "2.0"}, "nodes": nodes, "skins": [{"joints": list(range(len(nodes)))}]}
    js = json.dumps(g).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body)
    return path


@pytest.mark.skipif(not (BOSS / "bosses" / "barb" / "gear_test" / "barb_roles.json").is_file(),
                    reason="roles live on the Boss tree")
def test_real_roles_files_and_a_real_walk():
    from tools.boss_sprite_pipeline.rigging.map.skeleton import load_bvh
    barb = json.loads((BOSS / "bosses" / "barb" / "gear_test" / "barb_roles.json").read_text(encoding="utf-8"))
    demon = json.loads((BOSS / "bosses" / "demon" / "rig" / "jaw" / "bone_roles.json").read_text(encoding="utf-8"))
    sk = load_bvh((BOSS / "bosses" / "kimodo_new_blender" / "walk_v1_00.bvh").read_text(encoding="utf-8"))
    src = sources.label(sk.names, "soma")
    assert set(match(src, R.canonical(barb, "anun"), static=sources.soma.STATIC)["roles"]) == HUMAN_22
    assert set(match(src, R.canonical(demon, "demon_hand"), static=sources.soma.STATIC)["roles"]) == DEMON_20


def test_pod_packages_carry_the_bake_code_and_the_job():
    import io
    import tarfile
    from tools.boss_sprite_pipeline.rigging.pod import bake as PB
    names = tarfile.open(fileobj=io.BytesIO(PB.pack_code())).getnames()
    for need in ("tools/boss_sprite_pipeline/retarget_bvh.py", "tools/boss_sprite_pipeline/viewer/export_split.py",
                 "tools/boss_sprite_pipeline/rigging/map/transfer.py", "tools/boss_sprite_pipeline/rigging/pod/pod_side.py",
                 "tools/boss_sprite_pipeline/rigging/blender/pose_io.py"):
        assert need in names, need
    assert not any("__pycache__" in n for n in names)
