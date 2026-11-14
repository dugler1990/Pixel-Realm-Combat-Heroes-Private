"""A new character (kind character, .cursor/plans/new_character.plan.md): concept to TRELLIS so far.
No paid call, no pod. The concept check runs the pose venv (tools/boss_sprite_pipeline/.venv-pose) when it is there."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

from tools.boss_sprite_pipeline import concept_gate as cg
from tools.boss_sprite_pipeline import outfit as of
from tools.boss_sprite_pipeline import outfit_fields
from tools.boss_sprite_pipeline import outfit_web as ow

BOSS = Path(os.environ.get("OUTFIT_DATA_ROOT") or r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss")
BARB_FRONT = BOSS / "generated" / "bosses" / "barb" / "gear_test" / "body_sil" / "body_front_textured.png"
START = {"kind": "character", "view_prompts": "tools/boss_sprite_pipeline/view_prompts/character.json",
         "concept_config": "tools/painted_map_pipeline/openai.gpt-image-2.json", "concept_count": 2,
         "concept_prompt": "a hooded ice wizard with a staff", "trellis_models": ["front_back_sides"]}


def test_a_new_character_needs_no_rig_and_names_what_it_lacks():
    o = {"character": "w", "pack": "w_base", **START}
    assert outfit_fields.problems(o) == []
    for step in ("concept", "front", "back", "sides", "trellis"):
        assert outfit_fields.missing(o, step) == [], step
    lacking = {f.name for f in outfit_fields.needed({k: v for k, v in o.items() if k != "concept_prompt"})}
    assert "concept_prompt" in lacking and "rig_fit" not in lacking          # the rig is what it makes
    assert outfit_fields.missing({**o, "images": {"front": "f.png"}, "concept_prompt": None}, "concept") == []
    assert [s for s in of.STEPS["character"] if s not in of.RUN] == []
    assert set(of.STEPS["character"]) <= set(ow.STEP_UI) and set(outfit_fields.KINDS) == set(ow.KIND_UI)


def test_the_concept_prompt_carries_the_pose_and_the_look_images():
    block = json.loads((of.TOOLS / "view_prompts" / "character.json").read_text(encoding="utf-8"))["concept"]
    p = cg.build_prompt(block, "a hooded ice wizard", 0, None)
    assert p.startswith("a hooded ice wizard") and "Image 1" in p and "Image 2" not in p
    assert "Images 2 to 3" in cg.build_prompt(block, "x", 2, None)
    assert "Image 2 shows" in cg.build_prompt(block, "x", 1, None)
    assert "longer cloak" in cg.build_prompt(block, "x", 0, "longer cloak")
    assert (of.REPO / block["pose_ref"]).is_file()


def test_concept_dry_run(tmp_path):
    outfit = tmp_path / "base.json"
    outfit.write_text(json.dumps(START), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "tools.boss_sprite_pipeline.concept_gate", "--out", str(tmp_path / "c"),
                        "--outfit", str(outfit), "--dry-run"], cwd=of.REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("a hooded ice wizard") and "a_pose.png" in r.stderr and "2 candidates" in r.stderr
    outfit.write_text(json.dumps({**START, "concept_prompt": ""}), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "tools.boss_sprite_pipeline.concept_gate", "--out", str(tmp_path / "c"),
                        "--outfit", str(outfit), "--dry-run"], cwd=of.REPO, capture_output=True, text=True)
    assert r.returncode != 0 and "concept_prompt" in r.stderr


@pytest.mark.skipif(not (cg.POSE_PYTHON.exists() and BARB_FRONT.is_file()), reason="pose venv or barb front missing")
def test_the_concept_check_passes_the_barb_and_fails_a_cut_off_figure(tmp_path):
    limits = json.loads(cg.CHECKS.read_text(encoding="utf-8"))["concept"]
    cut = tmp_path / "cut.png"
    im = Image.open(BARB_FRONT).convert("RGB")
    im.crop((0, im.height // 3, im.width, im.height)).save(cut)                 # head and chest cut off
    found = cg.poses([BARB_FRONT, cut])
    good = cg.check(BARB_FRONT, found[str(BARB_FRONT)], limits)
    assert good["passed"], good["failing"]
    assert 18 <= good["arms"]["left"] <= 40 and good["people"] == 1
    bad = cg.check(cut, found[str(cut)], limits)
    assert not bad["passed"]


def character_ctx(tmp_path, monkeypatch, extra=None):
    monkeypatch.setenv("OUTFIT_DATA_ROOT", str(tmp_path))
    outfits = tmp_path / "outfits"
    (outfits / "wiz").mkdir(parents=True)
    (outfits / "wiz" / "character.json").write_text("{}", encoding="utf-8")
    (outfits / "wiz" / "base.json").write_text(json.dumps({"character": "wiz", "pack": "wiz_base", **START,
                                                           **(extra or {})}), encoding="utf-8")
    monkeypatch.setattr(of.characters, "OUTFITS", outfits)
    return of.Ctx("wiz", "base")


def test_the_accepted_concept_is_the_front_and_unbuilt_steps_say_so(tmp_path, monkeypatch, capsys):
    ctx = character_ctx(tmp_path, monkeypatch)
    cdir = ctx.work / "concept"
    calls = []

    def fake(cmd, ok=None, cwd=None, show=True):
        cmd = [str(c) for c in cmd]
        calls.append(cmd)
        if "concept_gate" in cmd[2]:
            cdir.mkdir(parents=True, exist_ok=True)
            gj = cdir / "gate_concept.json"
            if "--accept" in cmd:
                g = json.loads(gj.read_text(encoding="utf-8"))
                Image.new("RGB", (8, 8), "white").save(cdir / "concept.png")
                g.update(status="accepted", accepted=2, concept=str(cdir / "concept.png"))
            else:
                g = {"attempts": [{"attempt": 1, "draw": "a.png"}, {"attempt": 2, "draw": "b.png"}],
                     "status": "pending", "sheet": "s.png"}
            gj.write_text(json.dumps(g), encoding="utf-8")
            return "PENDING"
        gate_dir = Path(cmd[cmd.index("--out") + 1])
        gj = gate_dir / "gate_front.json"
        g = json.loads(gj.read_text(encoding="utf-8")) if gj.is_file() else {"attempts": []}
        if "--use" in cmd:
            g["attempts"].append({"attempt": 1, "draw": "f.png", "supplied": str(Path(cmd[cmd.index("--use") + 1]).resolve()),
                                  "scores": {"passed": False}})
            g["status"] = "pending"
        else:
            g.update(status="accepted", accepted=1)
        gate_dir.mkdir(parents=True, exist_ok=True)
        gj.write_text(json.dumps(g), encoding="utf-8")
        return "PENDING"
    monkeypatch.setattr(of, "call", fake)
    a = type("A", (), {"accept": None, "use": None, "retry": None, "view": None})()
    with pytest.raises(of.Stop, match="concept candidates"):
        of.s_concept(ctx, a)
    a.accept = 2
    of.s_concept(ctx, a)
    assert ctx.done("concept") and ctx.given("front") == cdir / "concept.png"
    a.accept = None
    of.view_gate(ctx, "front", a)                    # the concept, taken as is: nothing to check it against
    front = [c for c in calls if "view_gate" in c[2]]
    assert front[0][front[0].index("--input") + 1] == str(cdir / "concept.png") and "--accept" in front[1]
    assert ctx.done("front")
    with pytest.raises(SystemExit):
        of.main(["wiz", "base", "--only", "rig"])
    assert "not built yet" in capsys.readouterr().out


def test_your_front_skips_the_concept(tmp_path, monkeypatch):
    (tmp_path / "in").mkdir()
    Image.new("RGB", (8, 8), "white").save(tmp_path / "in" / "f.png")
    ctx = character_ctx(tmp_path, monkeypatch, {"images": {"front": "in/f.png"}})
    of.s_concept(ctx, type("A", (), {"accept": None, "use": None, "retry": None})())
    assert ctx.step("concept")["status"] == "skipped" and ctx.given("front") == tmp_path / "in" / "f.png"
