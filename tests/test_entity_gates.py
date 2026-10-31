"""The entity pipeline's review gates, with every paid call faked."""
from __future__ import annotations

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
