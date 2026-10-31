"""The entity pipeline's cut, frame fit, and map wire, without a paid image call."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

from tools.entity_pipeline.figures import BOX_TOLERANCE_PX, box_deltas, cut_sheet, find_light_figures
from tools.entity_pipeline.frames import fit_actions, foot_and_height, load_action, pack_monster
from tools.entity_pipeline.wire import add_placed_entity, format_entry, template_entry
from tools.painted_map_pipeline.leonardo_api import LeonardoApiError, video_generation_payload

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
