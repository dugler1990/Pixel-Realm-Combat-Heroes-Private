from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from tools.painted_map_pipeline.world_levels import compose as compose_mod
from tools.painted_map_pipeline.world_levels.compose import accept_composition, compose_level


def _run_root(tmp_path: Path) -> Path:
    """A minimal run root: a config with a generation block + a non-black accepted level image."""
    root = tmp_path / "run"
    accepted = root / "levels" / "01" / "accepted"
    accepted.mkdir(parents=True)
    art = np.full((32, 48, 4), (80, 80, 80, 255), dtype=np.uint8)  # non-black -> counts as land
    Image.fromarray(art, "RGBA").save(accepted / "image.png")
    (root / "config.json").write_text(
        json.dumps({"generation": {"provider": "openai", "model": "gpt-image-2"}}),
        encoding="utf-8",
    )
    return root


def test_compose_writes_attempt_then_accepts(monkeypatch, tmp_path: Path):
    root = _run_root(tmp_path)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Make it a desert with a set of pyramids.\n", encoding="utf-8")

    captured: dict = {}

    def fake_edit_image(*, prompt, input_images, mask, output_path, width, height, config):
        captured.update(prompt=prompt, size=(width, height), config=config, inputs=input_images)
        Image.new("RGB", (width, height), (10, 20, 30)).save(output_path)
        return {}

    monkeypatch.setattr(compose_mod, "edit_image", fake_edit_image)

    result = compose_level(root, "01", prompt_file)
    assert result["attempt"] == 1
    attempt_dir = root / "levels" / "01" / "composed" / "attempt_001"
    assert (attempt_dir / "composed.png").is_file()
    assert (attempt_dir / "prompt.txt").read_text(encoding="utf-8").strip() == (
        "Make it a desert with a set of pyramids."
    )
    # generated at the accepted image's own size, sending the accepted image itself
    assert captured["size"] == (48, 32)
    assert captured["config"]["model"] == "gpt-image-2"
    assert [Path(p).name for p in captured["inputs"]] == ["image.png"]
    # a player-scale review overlay is always written beside the output
    assert (attempt_dir / "composed_with_player.png").is_file()
    assert result["review_path"] == str(attempt_dir / "composed_with_player.png")

    assert compose_level(root, "01", prompt_file)["attempt"] == 2

    accepted = accept_composition(root, "01", 1)
    assert Path(accepted["composed_path"]).is_file()
    assert (root / "levels" / "01" / "composed" / "composed.png").is_file()


def test_compose_stamps_scale_anchor(monkeypatch, tmp_path: Path):
    root = _run_root(tmp_path)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("Desert with pyramids.\n", encoding="utf-8")
    sprite = tmp_path / "barb.png"
    fig = np.zeros((20, 10, 4), dtype=np.uint8)
    fig[2:18, 3:7] = (200, 150, 100, 255)  # opaque figure on transparent
    Image.fromarray(fig, "RGBA").save(sprite)

    captured: dict = {}

    def fake_edit_image(*, prompt, input_images, mask, output_path, width, height, config):
        captured.update(prompt=prompt, inputs=[str(p) for p in input_images])
        Image.new("RGB", (width, height), (0, 0, 0)).save(output_path)
        return {}

    monkeypatch.setattr(compose_mod, "edit_image", fake_edit_image)

    result = compose_level(root, "01", prompt_file, player_px=6, player_sprite=sprite, player_count=3)
    stamped = root / "levels" / "01" / "composed" / "attempt_001" / "input_stamped.png"
    assert stamped.is_file()
    # the stamped copy (not the raw accepted) is what gets sent
    assert captured["inputs"] == [str(stamped)]
    assert result["input_path"] == str(stamped)
    # the scale-reference instruction was appended to the prompt
    assert "figures" in captured["prompt"].lower() and "player" in captured["prompt"].lower()
    # a figure was actually drawn (stamped input differs from the accepted source)
    accepted = np.asarray(Image.open(root / "levels" / "01" / "accepted" / "image.png").convert("RGB"))
    stamped_arr = np.asarray(Image.open(stamped).convert("RGB"))
    assert not np.array_equal(accepted, stamped_arr)


def test_compose_requires_accepted_image(tmp_path: Path):
    root = tmp_path / "run"
    (root / "levels" / "01").mkdir(parents=True)
    (root / "config.json").write_text(json.dumps({"generation": {}}), encoding="utf-8")
    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("x", encoding="utf-8")
    try:
        compose_level(root, "01", prompt_file)
        assert False, "expected ValueError for missing accepted image"
    except ValueError as exc:
        assert "accepted image" in str(exc)
