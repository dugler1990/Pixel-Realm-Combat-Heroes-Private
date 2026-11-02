"""The entity pipeline's review gates, with every paid call faked."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from tools.entity_pipeline import cli as cli_mod
from tools.entity_pipeline import session as session_mod
from tools.painted_map_pipeline import leonardo_api

TMX = """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" nextobjectid="10">
 <objectgroup id="1" name="placed_entities">
  <object id="3" name="flyer_mid" x="10" y="20">
   <properties>
    <property name="entity_spawn_config" value="{&quot;kind&quot;:&quot;enemy&quot;,&quot;type&quot;:&quot;flyer&quot;}"/>
   </properties>
  </object>
 </objectgroup>
</map>
"""


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Fake both paid calls, keep sessions in tmp_path, and never open a viewer."""
    monkeypatch.setattr(session_mod, "WORK_ROOT", tmp_path / "work")
    monkeypatch.setattr(cli_mod, "show", lambda path: None)
    calls = []

    def fake_generate(prompt, sources, dest, config_path):
        calls.append({"prompt": prompt, "sources": list(sources)})
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8)).save(dest)
        return {"cost_usd": 0.0, "output_path": str(dest)}

    def fake_video(**kwargs):
        calls.append({"prompt": kwargs["prompt"], "sources": [kwargs["input_image"]]})
        kwargs["output_path"].write_bytes(b"clip")
        return {"cost_usd": 0.0, "output_path": str(kwargs["output_path"])}

    monkeypatch.setattr(cli_mod, "_generate", fake_generate)
    monkeypatch.setattr(leonardo_api, "generate_image_to_video", fake_video)
    image = tmp_path / "map.png"
    Image.new("RGB", (8, 8)).save(image)
    ref = tmp_path / "ref.png"
    Image.new("RGB", (8, 8)).save(ref)
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    return {
        "calls": calls,
        "image": image,
        "ref": ref,
        "common": ["--session", "s", "--config", str(config)],
        "work": tmp_path / "work" / "s",
        "tmp": tmp_path,
    }


def _answers(monkeypatch, *replies):
    queue = iter(replies)
    monkeypatch.setattr(cli_mod, "ask", lambda question, default="": next(queue))


def _never_ask(monkeypatch):
    def fail(question, default=""):
        raise AssertionError(f"asked: {question}")

    monkeypatch.setattr(cli_mod, "ask", fail)


def _scene(run, *extra):
    return cli_mod.main(["scene", *run["common"], "--image", str(run["image"]), *extra])


def _anim(run, *extra):
    return cli_mod.main(["anim", *run["common"], "--name", "w", "--sprite", str(run["image"]), *extra])


def test_scene_enter_keeps_the_first_draw(run, monkeypatch):
    _answers(monkeypatch, "")
    assert _scene(run) == 0
    assert len(run["calls"]) == 1
    assert run["calls"][0]["sources"] == [run["image"]]
    assert (run["work"] / "scene_prompt.txt").read_text(encoding="utf-8") == cli_mod.SCENE_PROMPT


def test_scene_redraw_with_criticism_moves_the_first_draw_aside(run, monkeypatch):
    _answers(monkeypatch, "r too dark", "")
    assert _scene(run) == 0
    assert len(run["calls"]) == 2
    second = run["calls"][1]["prompt"]
    assert second.startswith(cli_mod.SCENE_PROMPT)
    assert second.rstrip().endswith("too dark")
    assert (run["work"] / "scene_prompt.txt").read_text(encoding="utf-8") == second
    assert len(list((run["work"] / "old").glob("*/scene.png"))) == 1
    assert len(list((run["work"] / "old").glob("*/scene_prompt.txt"))) == 1


def test_scene_redraw_can_attach_an_image(run, monkeypatch):
    _answers(monkeypatch, f"r wrong colours @{run['ref']}", "")
    assert _scene(run) == 0
    assert run["calls"][1]["sources"] == [run["image"], run["ref"]]
    assert "IMAGE 2 IS ref.png." in run["calls"][1]["prompt"]


def test_scene_q_stops_with_exit_code_1(run, monkeypatch):
    _answers(monkeypatch, "q")
    assert _scene(run) == 1
    assert len(run["calls"]) == 1


def test_yes_draws_once_and_never_asks(run, monkeypatch):
    _never_ask(monkeypatch)
    assert _scene(run, "--yes") == 0
    assert len(run["calls"]) == 1


def test_anim_refuses_an_attached_image_and_q_stops_before_move(run, monkeypatch):
    _answers(monkeypatch, f"r slower @{run['ref']}", "q")
    assert _anim(run) == 1
    assert len(run["calls"]) == 1
    assert not (run["work"] / "anim" / "w" / "move.mp4").exists()


def test_anim_asks_once_per_clip(run, monkeypatch):
    _answers(monkeypatch, "", "", "")
    assert _anim(run) == 0
    assert len(run["calls"]) == 3
    for action in ("idle", "move", "attack"):
        assert (run["work"] / "anim" / "w" / f"{action}_prompt.txt").exists()


def test_cut_never_asks(run, monkeypatch):
    _never_ask(monkeypatch)
    monkeypatch.setattr(cli_mod, "cut_sheet", lambda image, out_dir: [])
    assert cli_mod.main(["cut", *run["common"], "--sheet", str(run["image"])]) == 0


def test_run_command_gets_through_cut(run, monkeypatch):
    _answers(monkeypatch, "", "")
    monkeypatch.setattr(cli_mod, "cut_sheet", lambda image, out_dir: [])
    assert cli_mod.main(["run", *run["common"], "--image", str(run["image"])]) == 0
    assert len(run["calls"]) == 2


def test_wire_q_leaves_the_map_alone(run, monkeypatch):
    tmx = run["tmp"] / "map.tmx"
    tmx.write_text(TMX, encoding="utf-8")
    _answers(monkeypatch, "q")
    assert cli_mod.main(["wire", *run["common"], "--name", "w", "--map", str(tmx)]) == 0
    assert tmx.read_text(encoding="utf-8") == TMX


def test_wire_yes_writes_the_map(run, monkeypatch):
    tmx = run["tmp"] / "map.tmx"
    tmx.write_text(TMX, encoding="utf-8")
    _never_ask(monkeypatch)
    assert cli_mod.main(["wire", *run["common"], "--name", "w", "--map", str(tmx), "--yes"]) == 0
    assert 'name="w"' in tmx.read_text(encoding="utf-8")


def _two_cells(run):
    cells = run["work"] / "cells"
    cells.mkdir(parents=True)
    for name in ("a", "b"):
        Image.new("RGB", (8, 8)).save(cells / f"{name}.png")


def test_all_animates_then_opens_the_brawl(run, monkeypatch):
    order = []
    monkeypatch.setattr(cli_mod, "cmd_anim_all", lambda args: order.append("anim") or 0)
    monkeypatch.setattr(cli_mod, "cmd_brawl", lambda args: order.append(("brawl", args.each)) or 0)
    _answers(monkeypatch, "")
    assert cli_mod.main(["all", *run["common"], "--each", "2"]) == 0
    assert order == ["anim", ("brawl", 2)]


def test_all_can_change_how_many_of_each_before_the_brawl(run, monkeypatch):
    order = []
    monkeypatch.setattr(cli_mod, "cmd_anim_all", lambda args: order.append("anim") or 0)
    monkeypatch.setattr(cli_mod, "cmd_brawl", lambda args: order.append(("brawl", args.each)) or 0)
    _answers(monkeypatch, "each 4", "")
    assert cli_mod.main(["all", *run["common"], "--each", "1"]) == 0
    assert order == ["anim", ("brawl", 4)]


def test_all_stops_before_the_brawl_when_animation_fails(run, monkeypatch):
    order = []
    monkeypatch.setattr(cli_mod, "cmd_anim_all", lambda args: order.append("anim") or 1)
    monkeypatch.setattr(cli_mod, "cmd_brawl", lambda args: order.append("brawl") or 0)
    assert cli_mod.main(["all", *run["common"]]) == 1
    assert order == ["anim"]


def test_brawl_launches_the_visible_validation_scenario(run, monkeypatch):
    from types import SimpleNamespace

    from tools.entity_pipeline import wire as wire_mod

    _two_cells(run)
    monkeypatch.chdir(run["tmp"])
    for name in ("a", "b"):
        (run["tmp"] / "Graphics" / "Monsters" / name / "idle").mkdir(parents=True)
    settings = run["tmp"] / "Settings.py"
    settings.write_text(
        'monster_data = {\n    "tribey_spear": {"health": 70, "attack_type": "melee"},\n}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(wire_mod, "SETTINGS", settings)
    launched = {}

    def fake_run(cmd, cwd, env, check=False):
        launched["cmd"] = cmd
        launched["cwd"] = cwd
        launched["roster"] = env["PRCH_ENTITY_BRAWL"]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(cli_mod, "cmd_anim_all", lambda args: 0)
    _answers(monkeypatch, "")
    assert cli_mod.main(["all", *run["common"], "--each", "1", "--hold", "12"]) == 0
    assert launched["cmd"][1:] == [
        "rts_validation.py", "--scenario", "warrior_brawl",
        "--layout-dir", "../levels/benchmark",
        "--hold-seconds", "12.0", "--max-seconds", "30",
    ]
    roster = json.loads(Path(launched["roster"]).read_text(encoding="utf-8"))
    assert {spot["type"] for spot in roster["spots"]} == {"a", "b"}
    assert {spot["team"] for spot in roster["spots"]} == {"enemy_1", "enemy_3"}


def test_anim_all_keeps_every_clip_without_asking(run, monkeypatch):
    _two_cells(run)
    framed = []
    monkeypatch.setattr(cli_mod, "cmd_frames", lambda args: framed.append(args.name) or 0)
    _never_ask(monkeypatch)
    assert cli_mod.main(["anim-all", *run["common"]]) == 0
    assert len(run["calls"]) == 6
    assert framed == ["a", "b"]
    for name in ("a", "b"):
        for action in ("idle", "move", "attack"):
            assert (run["work"] / "anim" / name / f"{action}.mp4").exists()


def test_fight_places_one_of_each_on_hostile_teams(run, monkeypatch):
    from tools.entity_pipeline import wire as wire_mod

    _two_cells(run)
    settings = run["tmp"] / "Settings.py"
    settings.write_text(
        'monster_data = {\n    "tribey_spear": {"health": 70, "attack_type": "melee"}\n}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(wire_mod, "SETTINGS", settings)
    tmx = run["tmp"] / "map.tmx"
    tmx.write_text(TMX, encoding="utf-8")
    assert cli_mod.main(["fight", *run["common"], "--map", str(tmx), "--each", "1"]) == 0
    written = tmx.read_text(encoding="utf-8")
    assert 'name="a"' in written
    assert 'name="b"' in written
    assert "enemy_1" in written
    assert "enemy_3" in written
    text = settings.read_text(encoding="utf-8")
    assert '"a"' in text and '"b"' in text
    assert text.count('"a"') == 1

    assert cli_mod.main(["fight", *run["common"], "--map", str(tmx), "--each", "1"]) == 0
    again = tmx.read_text(encoding="utf-8")
    assert again.count('name="a"') == 1
    assert settings.read_text(encoding="utf-8").count('"a"') == 1


def test_fight_each_keeps_copies_of_one_warrior_on_the_same_team(run, monkeypatch):
    from tools.entity_pipeline import wire as wire_mod

    _two_cells(run)
    settings = run["tmp"] / "Settings.py"
    settings.write_text(
        'monster_data = {\n    "tribey_spear": {"health": 70, "attack_type": "melee"},\n}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(wire_mod, "SETTINGS", settings)
    tmx = run["tmp"] / "map.tmx"
    tmx.write_text(TMX, encoding="utf-8")
    assert cli_mod.main(["fight", *run["common"], "--map", str(tmx), "--each", "2"]) == 0
    written = tmx.read_text(encoding="utf-8")
    assert 'name="a_1"' in written and 'name="a_2"' in written
    assert 'name="b_1"' in written and 'name="b_2"' in written
    a_team = written.split('name="a_1"', 1)[1].split('name="a_2"', 1)[0]
    assert a_team.count("enemy_1") == 1 or a_team.count("enemy_3") == 1
    assert "enemy_1" in written and "enemy_3" in written
