"""Cheap heightmap bakeoff helpers. No image API."""

import json
from pathlib import Path

import numpy as np
from PIL import Image

from tools.painted_map_pipeline.heightmap.run_cost import (
    run_variant,
    selected_variants,
    usd_from_api,
    write_contact_sheet,
    write_downscaled,
    write_log,
)


def test_usd_from_api_leonardo_and_openai():
    assert usd_from_api({"cost_usd": 0.0123}) == "0.0123"
    assert (
        usd_from_api(
            {
                "create_response": {
                    "generate": {"cost": {"amount": "0.0777", "unit": "DOLLARS"}}
                }
            }
        )
        == "0.0777"
    )
    assert usd_from_api({"usage": {"input_tokens": 1000, "output_tokens": 2500}}) == "0.1100"
    assert usd_from_api({}) == ""


def test_selected_variants_skips_risky_unless_asked():
    ids = [v["id"] for v in selected_variants(only=None, include_risky=False)]
    assert "leo_nb2_lite_1376x928" in ids
    assert "gpt2_low_1024x704" in ids
    assert "leo_phoenix_1024x768" not in ids
    risky = [v["id"] for v in selected_variants(only=None, include_risky=True)]
    assert "leo_phoenix_1024x768" in risky
    only = selected_variants(only="leo_phoenix_1024x768", include_risky=False)
    assert [v["id"] for v in only] == ["leo_phoenix_1024x768"]


def test_write_downscaled(tmp_path: Path):
    src = tmp_path / "source.png"
    Image.new("RGBA", (40, 20), (10, 20, 30, 255)).save(src)
    dest = tmp_path / "ref.png"
    write_downscaled(src, dest, (8, 4))
    with Image.open(dest) as im:
        assert im.size == (8, 4)


def test_run_variant_copy_writes_cost_folder(tmp_path: Path):
    src = np.zeros((32, 48, 4), dtype=np.uint8)
    src[:, :, 3] = 255
    src[8:20, 10:22, :3] = 200
    src[18:28, 24:40, :3] = 90
    source_path = tmp_path / "source.png"
    Image.fromarray(src, mode="RGBA").save(source_path)
    out_dir = tmp_path / "leo_copy"
    result = run_variant(
        variant={
            "id": "leo_copy",
            "note": "local copy",
            "overrides": {
                "provider": "copy",
                "model": "copy",
                "width": 48,
                "height": 32,
            },
        },
        base_config={"prompt": "unused", "qc_min_response": 0.0, "qc_max_shift_px": 8},
        source_path=source_path,
        out_dir=out_dir,
        preserve=False,
    )
    assert result["status"] == "OK"
    assert result["usd"] == ""
    assert result["qc"]["ok"]
    assert (out_dir / "heightmap.png").is_file()
    assert (out_dir / "heightmap_preview.png").is_file()
    dumped = json.loads((out_dir / "heightmap_result.json").read_text(encoding="utf-8"))
    assert dumped["id"] == "leo_copy"

    kept = run_variant(
        variant={"id": "leo_copy", "overrides": {"provider": "copy", "width": 48, "height": 32}},
        base_config={"prompt": "unused"},
        source_path=source_path,
        out_dir=out_dir,
        preserve=True,
    )
    assert kept.get("preserved") is True


def test_write_log_and_contact_sheet(tmp_path: Path):
    preview_dir = tmp_path / "demo"
    preview_dir.mkdir()
    Image.new("RGB", (20, 10), (80, 80, 80)).save(preview_dir / "heightmap_preview.png")
    rows = [
        {
            "when": "12:00:00",
            "status": "OK",
            "id": "demo",
            "provider": "copy",
            "model": "copy",
            "width": 20,
            "height": 10,
            "seconds": 0.1,
            "usd": "0.0000",
            "qc": {"dx": 0, "dy": 0, "response": 1.0, "ok": True},
            "note": "local",
        }
    ]
    log = write_log(tmp_path, rows)
    text = log.read_text(encoding="utf-8")
    assert "demo" in text
    assert "0.0000" in text
    sheet = write_contact_sheet(tmp_path, ["demo"])
    assert sheet is not None and sheet.is_file()
