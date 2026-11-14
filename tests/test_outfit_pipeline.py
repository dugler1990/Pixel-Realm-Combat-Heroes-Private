"""Outfit pipeline (tools/boss_sprite_pipeline/outfit.py, view_gate.py): step order, outfit files, gate retries.
No paid calls, no pod, no Blender."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.boss_sprite_pipeline import outfit as of

OUTFITS = Path(of.TOOLS) / "outfits"


def test_export_is_last_and_pod_steps_are_known():
    for kind, steps in of.STEPS.items():
        assert steps[-1] == "export", kind
        assert set(steps) <= set(of.RUN), kind
    assert of.STEPS["armour"].index("worn") > of.STEPS["armour"].index("merge")
    assert of.STEPS["armour"].index("slots") > of.STEPS["armour"].index("worn")
    assert of.POD_STEPS <= set(of.RUN)


@pytest.mark.parametrize("path", sorted(OUTFITS.glob("*/*.json")), ids=lambda p: p.stem)
def test_outfit_files_have_what_their_steps_read(path):
    o = json.loads(path.read_text(encoding="utf-8"))
    need = {"character", "kind", "roles", "rig_fit", "rig_game", "clips_blend", "pack"}
    need |= {"concept", "front", "back", "paint_look"} if o["kind"] in ("body", "armour") else {"source_mesh"}
    need |= {"greedy_dirs", "sam"} if o["kind"] in ("armour", "cut") else set()
    assert need <= set(o), need - set(o)
    if "prompt_to_part" in o.get("sam", {}):
        prompts = {p.replace(" ", "_") for crop in o["sam"]["prompts"].values() for p in crop}
        assert prompts <= set(o["sam"]["prompt_to_part"]), prompts - set(o["sam"]["prompt_to_part"])


def test_retry_choices_match_the_terminal_gate():
    from tools.boss_sprite_pipeline import view_gate as vg

    assert vg.retry_from("r", None, "front", False, vg.BIGGER, "front") == ("", [])
    assert vg.retry_from("rb", None, "front", False, vg.BIGGER, "front") == (vg.BIGGER, [])
    with pytest.raises(ValueError):
        vg.retry_from("rb", None, "front", False, None, "front")       # a body outfit has no "bigger armour"
    with pytest.raises(ValueError):
        vg.retry_from("rb", None, "front", True, vg.BIGGER, "front")   # a mask sets the size
    crit, attach = vg.retry_from("r the beard is too short", {"shape": None}, "front", False, None, "front")
    assert "beard" in crit and attach == []


def test_run_state_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTFIT_DATA_ROOT", str(tmp_path))
    ctx = of.Ctx("barb", "naked")
    assert ctx.work == tmp_path / "generated" / "bosses" / "barb" / "outfits" / "naked"
    assert not ctx.done("front")
    ctx.record("front", status="done", outputs={"draw": "x.png"})
    again = of.Ctx("barb", "naked")
    assert again.done("front") and again.out("front", "draw") == tmp_path / "x.png"
    with pytest.raises(of.Stop):
        again.out("back", "draw")


def test_models_decide_the_drawings(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTFIT_DATA_ROOT", str(tmp_path))
    ctx = of.Ctx("barb", "naked")
    assert ctx.models() == of.DEFAULT_MODELS == ["eight_views"]
    assert ctx.views() == ["front", "back", "left", "front_left", "back_left", "right", "front_right", "back_right"]
    ctx.run["models"] = ["front_only"]
    assert ctx.views() == ["front"]
    ctx.run["models"] = ["front_back", "front_back_sides"]
    assert ctx.views() == ["front", "back", "left", "right"]
    for v, src in of.MIRROR_OF.items():                                 # a mirrored view comes after its source
        assert of.SIDE_ORDER.index(src) < of.SIDE_ORDER.index(v)


def test_pod_step_stops_without_a_pod(monkeypatch):
    monkeypatch.delenv("POD_HOST", raising=False)
    monkeypatch.delenv("POD_PORT", raising=False)
    ctx = of.Ctx("barb", "naked")
    with pytest.raises(of.Stop, match="--host"):
        of.pod_args(ctx, type("A", (), {"host": None, "port": None})())
