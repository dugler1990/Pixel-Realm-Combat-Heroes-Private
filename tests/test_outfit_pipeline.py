"""Outfit pipeline (tools/boss_sprite_pipeline/outfit.py, view_gate.py): step order, outfit files, gate retries.
No paid calls, no pod, no Blender."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.boss_sprite_pipeline import characters, outfit_fields
from tools.boss_sprite_pipeline import outfit as of

OUTFITS = Path(of.TOOLS) / "outfits"


def test_export_is_last_and_pod_steps_are_known():
    for kind, steps in of.STEPS.items():
        assert steps[-2:] == ["export", "install"], kind
        assert set(steps) <= set(of.RUN), kind
    assert of.STEPS["armour"].index("worn") > of.STEPS["armour"].index("merge")
    assert of.STEPS["armour"].index("slots") > of.STEPS["armour"].index("worn")
    assert of.POD_STEPS <= set(of.RUN)


OUTFIT_FILES = sorted(p for p in OUTFITS.glob("*/*.json") if p.name != characters.FILE)


@pytest.mark.parametrize("path", OUTFIT_FILES, ids=lambda p: p.stem)
def test_outfit_files_have_what_their_steps_read(path):
    ctx = of.Ctx(path.parent.name, path.stem)
    o = ctx.o
    assert outfit_fields.problems(o) == []
    need = {"character", "kind", "roles", "rig_fit", "clips_blend", "pack"}
    need |= {"concept", "front", "back", "paint_look"} if o["kind"] in ("body", "armour") else {"source_mesh"}
    need |= {"greedy_dirs", "sam", "rig_game"} if o["kind"] in ("armour", "cut") else {"clips_from", "roster"}
    assert need <= set(o), need - set(o)
    own = json.loads(path.read_text(encoding="utf-8"))
    assert all(o[k] == v for k, v in own.items())                       # the outfit's own keys win
    assert o["character"] == path.parent.name
    if "prompt_to_part" in o.get("sam", {}):
        prompts = {p.replace(" ", "_") for crop in o["sam"]["prompts"].values() for p in crop}
        assert prompts <= set(o["sam"]["prompt_to_part"]), prompts - set(o["sam"]["prompt_to_part"])


def test_character_files_hold_what_their_outfits_share():
    for path in sorted(OUTFITS.glob(f"*/{characters.FILE}")):
        c = json.loads(path.read_text(encoding="utf-8"))
        assert all(outfit_fields.BY_NAME[k].level == "character" for k in c if not outfit_fields.is_note(k)), path
        for outfit in path.parent.glob("*.json"):
            if outfit.name != characters.FILE:                          # nothing repeated in an outfit file
                assert not (set(c) - {"_about"}) & set(json.loads(outfit.read_text(encoding="utf-8"))), outfit


def test_a_missing_field_is_named_never_filled_in():
    o = {"character": "x", "kind": "armour", "pack": "x_plate", "roles": "r.json", "clips_blend": "c.blend",
         "concept": "c.png", "paint_look": "l.json", "front": "f", "back": "b", "sam": {}, "greedy_dirs": "g.json",
         "rig_game": "g.glb"}
    assert outfit_fields.problems(o) == []                              # the rig is asked for by its steps
    bad = outfit_fields.missing(o, "skeleton")
    assert len(bad) == 1 and bad[0].startswith("no rig_fit (character file, read by skeleton, worn)")
    assert outfit_fields.missing(o, "front") == [] and [f.name for f in outfit_fields.needed(o)] == ["rig_fit"]
    assert outfit_fields.problems({**o, "colour": 1}) == ["unknown field 'colour'"]
    assert outfit_fields.problems({**o, "views": "32"}) == ["views must be a number"]
    assert outfit_fields.problems({**o, "kind": "hat"})[0].startswith("kind must be one of")
    assert outfit_fields.problems({"kind": "body"})[0].startswith("no character")  # read by every step
    assert outfit_fields.problems({**o, "images": {"top": "a.png"}})[0].startswith("images must be")
    with pytest.raises(SystemExit, match="clips.attack"):
        characters.need({"clips": {"idle": "a"}}, "x", "clips.attack")


def test_barb_character_rows_for_retarget_and_clips():
    row = characters.retarget_target("barb")
    assert row["rig"].endswith("barb_final_nb.glb") and row["bind_match"] is False and row["arm_elev_cap"] == 90.0
    assert characters.clip_choice("barb")["attack_frames"] == [[45, 60], [108, 138]]
    assert characters.retarget_target("demon") is None                  # bosses keep their code rows


def test_retry_choices_match_the_terminal_gate():
    from tools.boss_sprite_pipeline import view_gate as vg
    vg.load_prompts(vg.VIEW_PROMPTS / "barb_plate_armour.json")

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


def test_a_new_body_from_your_images_needs_no_prompt_concept_or_rig():
    o = {"character": "x", "kind": "body", "images": {"front": "f.png", "back": "b.png", "left": "l.png"}}
    assert outfit_fields.problems(o) == []
    for step in ("front", "back", "sides", "trellis"):
        assert outfit_fields.missing(o, step) == [], step
    assert {f.name for f in outfit_fields.needed({**o, "images": {"back": "b.png"}})} >= {"concept", "front"}
    assert "rig_fit" in [f.name for f in outfit_fields.needed(o)]       # still named, for the skeleton step


class FakeGate:
    """view_gate as the driver sees it: --use records an attempt (passing or not), --accept accepts it."""

    def __init__(self, gate_dir: Path, passed: bool):
        self.dir, self.passed, self.cmds = gate_dir, passed, []

    def __call__(self, cmd, ok=None, cwd=None, show=True):
        cmd = [str(c) for c in cmd]
        self.cmds.append(cmd)
        view = cmd[3] if cmd[3] != "side" else "side_" + cmd[cmd.index("--side") + 1]
        gj = self.dir / f"gate_{view}.json"
        gate = json.loads(gj.read_text(encoding="utf-8")) if gj.is_file() else {"attempts": []}
        if "--use" in cmd:
            n = len(gate["attempts"]) + 1
            gate["attempts"].append({"attempt": n, "draw": str(self.dir / f"{view}_{n}.png"),
                                     "supplied": str(Path(cmd[cmd.index("--use") + 1]).resolve()),
                                     "scores": {"passed": self.passed}})
            gate.update(status="pending", sheet="s.png")
        elif "--accept" in cmd:
            gate.update(status="accepted", accepted=int(cmd[cmd.index("--accept") + 1]))
            (self.dir / f"{view}.png").write_bytes(b"x")
        else:
            raise AssertionError(f"drew instead of using the image: {cmd}")
        self.dir.mkdir(parents=True, exist_ok=True)
        gj.write_text(json.dumps(gate), encoding="utf-8")
        return "PENDING"


def given_ctx(tmp_path, monkeypatch, images):
    monkeypatch.setenv("OUTFIT_DATA_ROOT", str(tmp_path))
    for rel in images.values():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    ctx = of.Ctx("barb", "naked")
    ctx.o = {**ctx.o, "images": images}
    ctx.o.pop("concept")
    ctx.run["models"] = ["front_back_sides"]
    return ctx


def test_your_images_are_used_not_drawn(tmp_path, monkeypatch):
    images = {"front": "in/f.png", "back": "in/b.png", "left": "in/l.png", "right": "in/r.png"}
    ctx = given_ctx(tmp_path, monkeypatch, images)
    gate = FakeGate(ctx.work / "gate", passed=True)
    monkeypatch.setattr(of, "call", gate)
    a = type("A", (), {"accept": None, "use": None, "retry": None, "view": None})()
    of.view_gate(ctx, "front", a)
    assert gate.cmds[0][gate.cmds[0].index("--input") + 1] == str(tmp_path / "in/f.png")   # no concept: its own
    assert "--use" in gate.cmds[0] and "--accept" in gate.cmds[1] and ctx.done("front")
    of.view_gate(ctx, "back", a)
    of.s_sides(ctx, a)
    assert ctx.done("back") and ctx.done("sides")
    assert (ctx.work / "gate" / "side_right.png").is_file()             # given, so not mirrored from the left
    assert sum("--use" in c for c in gate.cmds) == 4


def test_a_failed_check_on_your_image_waits_and_does_not_draw(tmp_path, monkeypatch):
    ctx = given_ctx(tmp_path, monkeypatch, {"front": "in/f.png", "back": "in/b.png"})
    ctx.o["concept"] = "in/f.png"                                       # a concept: the front is checked, here fails
    gate = FakeGate(ctx.work / "gate", passed=False)
    monkeypatch.setattr(of, "call", gate)
    a = type("A", (), {"accept": None, "use": None, "retry": None, "view": None})()
    with pytest.raises(of.Stop, match="front attempt 1"):
        of.view_gate(ctx, "front", a)
    with pytest.raises(of.Stop, match="front attempt 1"):               # again: still waiting, nothing drawn
        of.view_gate(ctx, "front", a)
    assert len(gate.cmds) == 1


def test_a_step_stops_naming_the_fields_it_reads(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("OUTFIT_DATA_ROOT", str(tmp_path))
    real = of.Ctx.__init__

    def no_rig(self, *a):
        real(self, *a)
        self.o.pop("rig_fit")
        self.record("trellis", status="done", outputs={"picked": "m.glb"})
    monkeypatch.setattr(of.Ctx, "__init__", no_rig)
    with pytest.raises(SystemExit) as stop:
        of.main(["barb", "naked", "--only", "skeleton"])
    assert stop.value.code == 2 and "no rig_fit (character file, read by skeleton" in capsys.readouterr().out


def test_view_prompts_and_checks_come_from_files_not_the_code(tmp_path):
    import subprocess
    import sys
    from tools.boss_sprite_pipeline import view_gate as vg
    src = Path(vg.__file__).read_text(encoding="utf-8")
    for barb in ("beard", "plate armour", "large chest", "gambeson"):            # no barb text left in the code
        assert barb not in src, barb
    checks = json.loads((Path(vg.CHECKS) / "default.json").read_text(encoding="utf-8"))
    vg.load_checks(Path(vg.CHECKS) / "default.json")
    assert vg.FRONT_MAX_MISSING == checks["front_max_missing"] == 0.02 and vg.HEAD == 0.13
    for o in ("fullplate", "naked"):                                             # the drawn barb outfits name it
        assert json.loads((OUTFITS / "barb" / f"{o}.json").read_text(encoding="utf-8"))["view_prompts"]
    outfit = tmp_path / "plain.json"
    outfit.write_text(json.dumps({"kind": "body"}), encoding="utf-8")
    img = tmp_path / "x.png"
    from PIL import Image
    Image.new("RGB", (64, 128), "white").save(img)
    r = subprocess.run([sys.executable, "-m", "tools.boss_sprite_pipeline.view_gate", "back", "--front", str(img),
                        "--out", str(tmp_path / "o"), "--outfit", str(outfit), "--dry-run"],
                       cwd=of.REPO, capture_output=True, text=True)
    assert r.returncode != 0 and "no back prompt" in r.stderr                    # named, never a barb default


def test_pod_step_stops_without_a_pod(monkeypatch):
    monkeypatch.delenv("POD_HOST", raising=False)
    monkeypatch.delenv("POD_PORT", raising=False)
    ctx = of.Ctx("barb", "naked")
    with pytest.raises(of.Stop, match="--host"):
        of.pod_args(ctx, type("A", (), {"host": None, "port": None})())


def test_the_hero_entry_comes_from_the_character_file_not_the_barb():
    from types import SimpleNamespace

    from tools.boss_sprite_pipeline import export_outfit as eo

    roster = {"display_name": "Ice wizard", "painting": "wizard.png", "player_info_dir": "../Graphics/wizard/",
              "roster_stats": ["magic"], "evasion_loadout": ["blink"], "base_stats": {"health": 900}}
    o = {"pack": "wizard_robe", "roster": roster}
    entry = eo.hero_entry(o, SimpleNamespace(character="wizard", outfit="robe"))
    assert entry["display_name"] == "Ice wizard (robe, mesh)" and entry["painting"] == "wizard.png"
    assert "barb" not in json.dumps(entry).lower()
    with pytest.raises(SystemExit, match="roster has no painting"):
        eo.hero_entry({**o, "roster": {k: v for k, v in roster.items() if k != "painting"}},
                      SimpleNamespace(character="wizard", outfit="robe"))


def test_a_look_is_required_and_can_extend_another(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("look_file", Path(of.TOOLS) / "repaint" / "look_file.py")
    lf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lf)
    with pytest.raises(SystemExit, match="no look file"):
        lf.load_look(None)
    base = {k: k for k in lf.REQUIRED}
    (tmp_path / "base.json").write_text(json.dumps({"_about": "base", **base}), encoding="utf-8")
    (tmp_path / "robe.json").write_text(json.dumps({"extends": "base.json", "design": "blue robe"}), encoding="utf-8")
    look = lf.load_look(tmp_path / "robe.json")
    assert look["design"] == "blue robe" and look["subject"] == "subject" and "_about" not in look
    (tmp_path / "bad.json").write_text(json.dumps({"subject": "x"}), encoding="utf-8")
    with pytest.raises(SystemExit, match="has no design"):
        lf.load_look(tmp_path / "bad.json")


# --- install: into the game -------------------------------------------------------------------------------------

def test_install_appends_stats_and_heroes_leaving_the_files_as_they_were(tmp_path, monkeypatch):
    from tools.boss_sprite_pipeline import install_outfit as io
    bases, sel = tmp_path / "item_bases.json", tmp_path / "sel.json"
    bases.write_bytes(io.BASES.read_bytes())
    sel.write_bytes(io.SELECTION.read_bytes())
    leather = {"name": "Leather chest", "set": None, "stopping_power": 12, "absorb": 0.35, "weight": 4,
               "coverage": ["chest", "back"], "conductivity": 0, "insulation": 0.4, "flammability": 0.5,
               "sealed": False, "durability": 150}
    before = bases.read_bytes()
    assert io.add_bases({"leather_chest": leather}, bases) == ["leather_chest"]
    after = bases.read_bytes()
    assert after.startswith(before.rstrip()[:-1].rstrip()) and json.loads(after)["leather_chest"] == leather
    for bad, why in (({"leather_chest": leather}, "already"), ({"x": {**leather, "shine": 1}}, "unknown field"),
                     ({"x": {**leather, "absorb": 3}}, "0 to 1"), ({"x": {**leather, "coverage": ["tail"]}}, "list of")):
        with pytest.raises(ValueError, match=why):
            io.add_bases(bad, bases)
    entry = {"name": "barb_test_mesh", "mesh_pack": "barb_test", "display_name": "T", "selection_position": {}}
    raw = sel.read_bytes()
    added = io.add_hero(entry, sel)
    data = json.loads(sel.read_text(encoding="utf-8"))
    taken = [(p["selection_position"]["x"], p["selection_position"]["y"]) for p in data["Players"][:-1]]
    assert data["Players"][-1] == added and (added["selection_position"]["x"], 0) not in taken
    assert sel.read_bytes().startswith(raw[:raw.rfind(b"]")].rstrip())    # the hand-made entries untouched
    with pytest.raises(ValueError, match="already"):
        io.add_hero(entry, sel)


def test_install_needs_the_stats_of_every_piece(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from tools.boss_sprite_pipeline import install_outfit as io
    (tmp_path / "packs").mkdir()
    (tmp_path / "packs" / "slot_packs.json").write_text(json.dumps({"chest": {}, "boot_l": {}, "boot_r": {}}))
    ctx = SimpleNamespace(work=tmp_path, o={"material": "plate"})
    assert io.needed_bases(ctx) == ["plate_boot", "plate_chest"] and io.missing_bases(ctx) == []
    ctx.o["material"] = "leather"
    assert io.missing_bases(ctx) == ["leather_boot", "leather_chest"]
    recorded = {}
    ctx.record = lambda step, **kw: recorded.update(kw)
    ctx.o["kind"] = "armour"
    with pytest.raises(of.Stop, match="no stats yet for leather_boot, leather_chest"):
        of.s_install(ctx, SimpleNamespace(accept=None))
    assert recorded["missing_bases"] == ["leather_boot", "leather_chest"]
