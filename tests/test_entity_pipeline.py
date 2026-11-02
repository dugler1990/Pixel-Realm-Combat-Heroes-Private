"""The entity pipeline's cut, frame fit, and map wire, without a paid image call."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tools.entity_pipeline.figures import BOX_TOLERANCE_PX, box_deltas, cut_sheet, find_light_figures
from tools.entity_pipeline.frames import fit_actions, foot_and_height, load_action, pack_monster
from tools.entity_pipeline.wire import (
    add_placed_entity,
    copies_for,
    fight_placements,
    roster_counts,
    format_entry,
    install_monster_entries,
    template_entry,
)
from tools.painted_map_pipeline.leonardo_api import (
    GAME_2D_STYLE_ID,
    LeonardoApiError,
    video_generation_payload,
)

NECRON_SHEET = Path(
    r"C:\Users\Douglas\Downloads\gpt-image-2.5-flare_concept_design_sheet_1.4_"
    r"concept_art_for_each_distinct_enemy_on_this_sheet_i_wou-0.jpg"
)
HAND_LAYOUT = Path("generated/entity_sheets/necron_faction/layout.json")


def _black_row_sheet() -> Image.Image:
    """Three figures on black, with a gap the gutter cutter can see."""
    image = Image.new("RGB", (420, 180), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    for x in (20, 160, 300):
        draw.rectangle([x, 30, x + 80, 150], fill=(180, 170, 150))
        draw.rectangle([x + 30, 130, x + 50, 155], fill=(140, 90, 50))
    return image


def _figure(width: int, height: int, foot_x: int, foot_y: int, sword: int = 0) -> Image.Image:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle([foot_x - 12, foot_y - 40, foot_x + 12, foot_y], fill=(40, 40, 50, 255))
    if sword:
        draw.rectangle([foot_x + 14, foot_y - 10, foot_x + 18, foot_y + sword], fill=(180, 180, 190, 255))
    return image


def test_frame_fit_shares_one_canvas_and_one_foot_point(tmp_path: Path):
    idle = [
        _figure(80, 70, 30, 50),
        _figure(90, 80, 40, 60),
    ]
    move = [_figure(100, 90, 20, 70, sword=12)]
    attack = [_figure(70, 60, 35, 45)]
    fitted = fit_actions({"idle": idle, "move": move, "attack": attack})
    size = fitted["idle"][0].size
    assert all(frame.size == size for frames in fitted.values() for frame in frames)
    feet = [foot_and_height(frame)[:2] for frames in fitted.values() for frame in frames]
    assert len(set(feet)) == 1
    monster = pack_monster("fit_test", fitted, root=tmp_path / "fit_test")
    for action, frames in fitted.items():
        written = sorted((monster / action).glob("*.png"))
        assert len(written) == len(frames)
        assert Image.open(written[0]).size == size


def test_veo_payload_starts_on_the_sprite_and_lasts_four_seconds():
    body = video_generation_payload(prompt="walk", image_id="sprite-1")
    assert body["model"] == "veo-3.1-lite"
    params = body["parameters"]
    assert params["duration"] == 4
    assert params["width"] == 1280 and params["height"] == 720
    assert params["motion_has_audio"] is False
    assert params["guidances"]["start_frame"] == [
        {"image": {"id": "sprite-1", "type": "UPLOADED"}}
    ]
    assert params["style_ids"] == [GAME_2D_STYLE_ID]
    eight = video_generation_payload(
        prompt="walk", image_id="sprite-1", seconds=8, model="veo-3.1-generate-001",
    )
    assert eight["parameters"]["duration"] == 8
    with pytest.raises(LeonardoApiError):
        video_generation_payload(prompt="walk", image_id="sprite-1", seconds=5)


def test_black_sheet_splits_on_the_gaps(tmp_path: Path):
    sheet = tmp_path / "row.png"
    _black_row_sheet().save(sheet)
    frames = load_action(sheet)
    assert len(frames) == 3
    assert frames[0].mode == "RGBA"


def test_wire_prints_tribey_spear_and_adds_one_object(tmp_path: Path):
    entry = template_entry("tribey_spear")
    assert entry["attack_type"] == "melee"
    text = format_entry("beastman_warrior", entry)
    assert '"beastman_warrior"' in text
    assert "health" in text

    tmx = tmp_path / "map.tmx"
    tmx.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<map version="1.10" nextobjectid="10">
 <objectgroup id="1" name="placed_entities">
  <object id="3" name="flyer_mid" x="10" y="20">
   <properties>
    <property name="entity_spawn_config" value="{&quot;kind&quot;:&quot;enemy&quot;,&quot;type&quot;:&quot;flyer&quot;}"/>
   </properties>
  </object>
 </objectgroup>
</map>
""",
        encoding="utf-8",
    )
    object_id = add_placed_entity(tmx, "beastman_warrior", x=1800, y=3400)
    assert object_id == 10
    written = tmx.read_text(encoding="utf-8")
    assert 'nextobjectid="11"' in written
    assert 'name="beastman_warrior" x="1800" y="3400"' in written
    assert '"type":"beastman_warrior"' in written or "&quot;beastman_warrior&quot;" in written
    with pytest.raises(SystemExit):
        add_placed_entity(tmx, "beastman_warrior", x=1, y=1)

    bare = tmp_path / "bare.tmx"
    bare.write_text('<map version="1.10" nextobjectid="1">\n</map>\n', encoding="utf-8")
    with pytest.raises(SystemExit, match="placed_entities"):
        add_placed_entity(bare, "beastman_warrior")


def test_video_matte_drops_the_border_and_keeps_the_figure():
    from tools.entity_pipeline.frames import _crop_union, _matte_border

    image = Image.new("RGB", (80, 60), (40, 40, 42))
    draw = ImageDraw.Draw(image)
    draw.rectangle([30, 12, 48, 48], fill=(180, 40, 30))
    draw.point((39, 28), fill=(40, 40, 42))
    matted = _matte_border(image)
    alpha = np.asarray(matted)[:, :, 3]
    assert alpha[0, 0] == 0
    assert alpha[28, 39] == 255
    cropped = _crop_union([matted])[0]
    assert cropped.size[0] < 40
    assert cropped.size[1] < 50
    cell = _figure(40, 36, 20, 30)
    target = foot_and_height(cell)[2]
    fitted = fit_actions(
        {"idle": [cropped], "move": [cropped], "attack": [cropped]},
        target,
    )
    _fx, _fy, height = foot_and_height(fitted["idle"][0])
    assert abs(height - target) <= 2
    assert fitted["idle"][0].size[1] < 80


def test_battle_scale_uses_the_men_and_applies_to_a_machine():
    from tools.entity_pipeline.frames import battle_scale, sheet_man_height

    scene = Image.new("RGB", (400, 400), (210, 170, 100))
    draw = ImageDraw.Draw(scene)
    for x in range(20, 300, 36):
        draw.rectangle([x, 250, x + 14, 290], fill=(30, 20, 15))
    draw.rectangle([300, 320, 370, 344], fill=(30, 20, 15))
    men = []
    for _i in range(3):
        man = Image.new("RGBA", (60, 210), (0, 0, 0, 0))
        ImageDraw.Draw(man).rectangle([16, 8, 44, 204], fill=(40, 40, 50, 255))
        men.append(man)
    machine = Image.new("RGBA", (180, 90), (0, 0, 0, 0))
    ImageDraw.Draw(machine).rectangle([4, 20, 170, 70], fill=(80, 50, 30, 255))
    assert sheet_man_height(men + [machine]) == foot_and_height(men[0])[2]
    scale = battle_scale(scene, men + [machine])
    assert abs(scale - 40 / foot_and_height(men[0])[2]) < 0.05
    machine_target = round(foot_and_height(machine)[2] * scale)
    assert machine_target < foot_and_height(machine)[2]
    middle = Image.new("RGB", (400, 400), (210, 170, 100))
    draw = ImageDraw.Draw(middle)
    for x in range(100, 300, 24):
        draw.rectangle([x, 120, x + 14, 160], fill=(30, 20, 15))
    assert battle_scale(middle, men, "center") > 0
    with pytest.raises(RuntimeError):
        battle_scale(middle, men, "near")


def test_a_score_sets_the_height_and_a_missing_one_keeps_the_drawing():
    from tools.entity_pipeline.frames import height_times_man

    assert height_times_man(1.8, 107, 100) == 1.8
    assert height_times_man(None, 107, 100) == pytest.approx(1.07)


def test_matte_clears_a_field_coloured_hole_and_keeps_armour():
    from tools.entity_pipeline.frames import _matte_border

    image = Image.new("RGB", (80, 60), (240, 230, 200))
    draw = ImageDraw.Draw(image)
    draw.rectangle([8, 6, 72, 54], fill=(180, 40, 30))
    draw.rectangle([34, 20, 48, 40], fill=(240, 230, 200))
    draw.rectangle([14, 16, 28, 30], fill=(70, 70, 74))
    alpha = np.asarray(_matte_border(image))[:, :, 3]
    assert alpha[0, 0] == 0
    assert alpha[30, 40] == 0
    assert alpha[22, 20] == 255
    assert alpha[12, 12] == 255


def test_matte_clears_every_colour_sitting_on_the_border():
    from tools.entity_pipeline.frames import _matte_border

    image = Image.new("RGB", (40, 30), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle([8, 0, 32, 29], fill=(240, 230, 200))
    draw.rectangle([16, 8, 24, 24], fill=(180, 40, 30))
    alpha = np.asarray(_matte_border(image))[:, :, 3]
    assert alpha[0, 0] == 0
    assert alpha[0, 20] == 0
    assert alpha[16, 20] == 255


def test_fight_splits_two_warriors_across_hostile_teams():
    spots = fight_placements(["a", "b"], 1, x=1800, y=3400)
    by_name = {spot["name"]: spot for spot in spots}
    assert set(by_name) == {"a", "b"}
    assert {by_name["a"]["team_id"], by_name["b"]["team_id"]} == {"enemy_1", "enemy_3"}
    assert by_name["a"]["entity_type"] == "a"


def test_one_warrior_with_several_copies_is_split_across_the_teams():
    spots = fight_placements(["a"], 2, x=1800, y=3400)
    assert [spot["name"] for spot in spots] == ["a_1", "a_2"]
    assert {spot["team_id"] for spot in spots} == {"enemy_1", "enemy_3"}


def test_label_picks_how_many_copies():
    assert copies_for("Tribal Spearman", "melee") == 3
    assert copies_for("Egyptian Archer", "ranged") == 2
    assert copies_for("Camel-Mounted Spearman", "melee") == 2
    assert copies_for("Camel-Mounted Archer", "ranged") == 1
    assert copies_for("Magic-User", "ranged") == 1
    assert copies_for("High Priest", "ranged") == 1
    assert copies_for("Catapult Machine", "ranged") == 1
    assert copies_for("Catapult Crewmember", "ranged") == 2


def test_roster_keeps_foot_above_horse_above_mage_above_catapult():
    counts = roster_counts({
        "spear": {"label": "Spearman", "reach": "melee"},
        "camel": {"label": "Camel Rider", "reach": "melee"},
        "mage": {"label": "Magic-User", "reach": "ranged"},
        "catapult": {"label": "Catapult Machine", "reach": "ranged"},
    })
    assert counts["spear"] > counts["camel"] > counts["mage"] > counts["catapult"]
    melee = counts["spear"] + counts["camel"]
    ranged = counts["mage"] + counts["catapult"]
    assert melee > ranged


def test_brawl_counts_follow_the_label():
    spots = fight_placements(
        ["archer", "catapult"],
        1,
        x=0,
        y=0,
        counts={"archer": 3, "catapult": 1},
        packed=True,
    )
    assert sum(spot["entity_type"] == "archer" for spot in spots) == 3
    assert sum(spot["entity_type"] == "catapult" for spot in spots) == 1
    for spot in spots:
        assert abs(spot["x"]) <= 340
        assert abs(spot["y"]) <= 340


def test_packed_brawl_stays_inside_the_wall_ring():
    spots = fight_placements([f"warrior_{i:02d}" for i in range(20)], 1, x=0, y=0, packed=True)
    assert len(spots) == 20
    for spot in spots:
        assert abs(spot["x"]) <= 340
        assert abs(spot["y"]) <= 340
    left = [spot["x"] for spot in spots if spot["team_id"] == "enemy_1"]
    right = [spot["x"] for spot in spots if spot["team_id"] == "enemy_3"]
    assert max(left) < 0 < min(right)


def test_install_monster_entries_adds_missing_names_once(tmp_path, monkeypatch):
    from tools.entity_pipeline import wire as wire_mod

    settings = tmp_path / "Settings.py"
    settings.write_text(
        'monster_data = {\n    "tribey_spear": {"health": 70}\n}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(wire_mod, "SETTINGS", settings)
    assert install_monster_entries(["a"], "tribey_spear") == ["a"]
    assert install_monster_entries(["a"], "tribey_spear") == []
    text = settings.read_text(encoding="utf-8")
    assert text.count('"a"') == 1
    tree_ok = compile(text, str(settings), "exec")
    assert tree_ok is not None


@pytest.mark.skipif(not NECRON_SHEET.exists() or not HAND_LAYOUT.exists(), reason="Necron fixture is local")
def test_necron_cut_matches_the_hand_boxes_and_drops_the_parchment(tmp_path: Path):
    sheet = Image.open(NECRON_SHEET)
    figures = find_light_figures(sheet)
    hand = json.loads(HAND_LAYOUT.read_text(encoding="utf-8"))["named_boxes"]
    hand_boxes = [(name, tuple(box)) for name, box in hand]
    deltas = box_deltas([fig.box for fig in figures], hand_boxes)
    assert len(figures) == 15
    for name, delta in deltas:
        assert max(delta) <= BOX_TOLERANCE_PX, f"{name} off by {delta}"

    cut_sheet(sheet, tmp_path)
    cells = list((tmp_path / "cells").glob("*.png"))
    assert len(cells) == 15
    assert (tmp_path / "contact.png").exists()
    colour = np.array([229, 214, 184], dtype=np.float32)
    for path in cells:
        sprite = np.asarray(Image.open(path).convert("RGBA"))
        alpha = sprite[:, :, 3]
        assert alpha.max() > 0
        opaque = alpha > 16
        # The parchment is gone.
        if opaque.any():
            dist = np.abs(sprite[:, :, :3].astype(np.float32) - colour).max(axis=2)
            assert float((opaque & (dist < 18)).mean()) < 0.01
        # The caption is a detached short strip. A clean sprite has one body.
        from scipy import ndimage

        labels, count = ndimage.label(opaque)
        if count == 0:
            pytest.fail(f"{path.name} is empty")
        sizes = ndimage.sum(np.ones_like(opaque), labels, index=np.arange(1, count + 1))
        objects = ndimage.find_objects(labels)
        for idx, size in enumerate(sizes, start=1):
            sl = objects[idx - 1]
            if sl is None or size <= 20:
                continue
            height = sl[0].stop - sl[0].start
            assert not (height <= 14 and sl[0].start > sprite.shape[0] * 0.72), (
                f"{path.name} still has a caption"
            )


def test_stats_reply_maps_onto_entries():
    import copy

    from tools.entity_pipeline.stats import StatsClientError, parse_scores
    from tools.entity_pipeline.wire import adjust_entry, template_entry

    names = [f"warrior_{i:02d}" for i in range(20)]
    rows = [{"cell": i, "label": "x", "speed": 5, "damage": 5, "bulk": 5, "reach": "melee", "size": 1} for i in range(20)]
    rows[0].update(speed=10, reach="ranged")
    rows[1].update(speed=1, damage=10, bulk=10)
    scores = parse_scores(json.dumps({"warriors": rows}), names)

    entry = template_entry("tribey_spear")
    before = copy.deepcopy(entry)
    ranged = adjust_entry(entry, scores["warrior_00"])
    assert ranged["speed"] == 6
    assert ranged["attack_type"] == "ranged"
    assert ranged["combat_config"]["ranged_attacks"][0]["type"] == "arrow"
    spell = {"speed": 5, "damage": 5, "bulk": 5, "reach": "ranged"}
    assert adjust_entry(entry, {**spell, "label": "Magic-User"})["combat_config"]["ranged_attacks"][0]["type"] == "demon_dog_projectile"
    assert adjust_entry(entry, {**spell, "label": "High Priest"})["combat_config"]["ranged_attacks"][0]["type"] == "demon_dog_projectile"
    assert adjust_entry(entry, {**spell, "label": "Catapult Machine"})["combat_config"]["ranged_attacks"][0]["type"] == "stone"
    assert ranged["combat_config"]["combat_context"]["fire_projectile"] is True
    melee = adjust_entry(entry, scores["warrior_01"])
    assert melee["speed"] == 2
    assert melee["health"] == 140
    assert melee["combat_config"]["melee_attacks"][0]["damage"] == 12
    assert entry == before

    with pytest.raises(StatsClientError):
        parse_scores(json.dumps({"warriors": rows[:19]}), names)


def test_folder_name_comes_back_in_the_score_and_renames_the_cell(tmp_path):
    from tools.entity_pipeline.stats import adopt_names, parse_scores

    names = ["warrior_00", "warrior_01"]
    rows = [
        {"cell": 0, "label": "Egyptian Spearman", "name": "Egyptian Spearman", "speed": 5, "damage": 6, "bulk": 4, "reach": "melee", "size": 1},
        {"cell": 1, "label": "Camel Archer", "name": "camel archer", "speed": 6, "damage": 4, "bulk": 3, "reach": "ranged", "size": 1.6},
    ]
    scores = parse_scores(json.dumps({"warriors": rows}), names)
    assert scores["warrior_00"]["name"] == "egyptian_spearman"
    assert scores["warrior_01"]["name"] == "camel_archer"

    work = tmp_path / "session"
    cells_dir = work / "cells"
    cells_dir.mkdir(parents=True)
    (cells_dir / "warrior_00.png").write_bytes(b"a")
    (cells_dir / "warrior_01.png").write_bytes(b"b")
    (work / "anim" / "warrior_00").mkdir(parents=True)
    monsters = tmp_path / "Monsters"
    (monsters / "warrior_01").mkdir(parents=True)
    layout = {"named_boxes": [["warrior_00", [0, 0, 1, 1]], ["warrior_01", [2, 0, 3, 1]]]}
    (work / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    cells = [("warrior_00", (0, 0, 1, 1)), ("warrior_01", (2, 0, 3, 1))]
    new_cells, new_scores, renamed = adopt_names(work, cells, scores, monsters)
    assert renamed == [("warrior_00", "egyptian_spearman"), ("warrior_01", "camel_archer")]
    assert (cells_dir / "egyptian_spearman.png").read_bytes() == b"a"
    assert (work / "anim" / "egyptian_spearman").is_dir()
    assert (monsters / "camel_archer").is_dir()
    assert new_scores["camel_archer"]["label"] == "Camel Archer"
    assert new_cells[0][0] == "egyptian_spearman"
    saved = json.loads((work / "layout.json").read_text(encoding="utf-8"))
    assert saved["named_boxes"][1][0] == "camel_archer"


def test_rescore_rewrites_an_existing_copy(tmp_path, monkeypatch):
    from tools.entity_pipeline import wire as wire_mod

    settings = tmp_path / "Settings.py"
    settings.write_text(
        'monster_data = {\n'
        '    "tribey_spear": {"health": 70, "speed": 15, "attack_type": "melee", '
        '"combat_config": {"melee_attacks": [{"damage": 6, "cooldown": 1000}], '
        '"ranged_attacks": [], "combat_context": {}}}\n'
        '}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(wire_mod, "SETTINGS", settings)
    install_monster_entries(["warrior_00"], "tribey_spear")
    score = {"label": "archer", "speed": 10, "damage": 1, "bulk": 1, "reach": "ranged"}
    changed = wire_mod.rescore_monster_entries({"warrior_00": score, "tribey_spear": score}, "tribey_spear")
    assert changed == ["warrior_00"]
    namespace = {}
    exec(settings.read_text(encoding="utf-8"), namespace)
    assert namespace["monster_data"]["warrior_00"]["attack_type"] == "ranged"
    assert namespace["monster_data"]["tribey_spear"]["speed"] == 15
    assert wire_mod.rescore_monster_entries({"warrior_00": score}, "tribey_spear") == []


def test_load_scores_rejects_a_changed_sheet_or_box(tmp_path):
    from tools.entity_pipeline.stats import load_scores, save_scores

    work = tmp_path / "session"
    work.mkdir()
    sheet = work / "sheet.png"
    sheet.write_bytes(b"same-pixels")
    cells = [("warrior_00", (0, 0, 10, 20))]
    layout = {"named_boxes": [["warrior_00", [0, 0, 10, 20]]]}
    (work / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    score = {"warrior_00": {"label": "x", "speed": 5, "damage": 5, "bulk": 5, "reach": "melee"}}
    save_scores(work, "gpt-5-mini", sheet, cells, score)
    assert load_scores(work) == score

    sheet.write_bytes(b"new-pixels")
    assert load_scores(work) == {}

    sheet.write_bytes(b"same-pixels")
    layout["named_boxes"] = [["warrior_00", [0, 0, 10, 40]]]
    (work / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
    assert load_scores(work) == {}

