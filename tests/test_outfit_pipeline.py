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
    bad = outfit_fields.problems(o)
    assert len(bad) == 1 and bad[0].startswith("no rig_fit (character file)")
    assert outfit_fields.problems({**o, "rig_fit": "f.glb", "colour": 1}) == ["unknown field 'colour'"]
    assert outfit_fields.problems({**o, "rig_fit": "f.glb", "views": "32"}) == ["views must be a number"]
    assert outfit_fields.problems({**o, "kind": "hat"})[0].startswith("kind must be one of")
    with pytest.raises(SystemExit, match="clips.attack"):
        characters.need({"clips": {"idle": "a"}}, "x", "clips.attack")


def test_barb_character_rows_for_retarget_and_clips():
    row = characters.retarget_target("barb")
    assert row["rig"].endswith("barb_final_nb.glb") and row["bind_match"] is False and row["arm_elev_cap"] == 90.0
    assert characters.clip_choice("barb")["attack_frames"] == [[45, 60], [108, 138]]
    assert characters.retarget_target("demon") is None                  # bosses keep their code rows


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
