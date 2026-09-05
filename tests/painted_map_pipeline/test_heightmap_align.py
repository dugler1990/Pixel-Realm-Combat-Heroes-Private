"""Heightmap align + QC. No image API."""

from pathlib import Path

import numpy as np
from PIL import Image

from tools.painted_map_pipeline.heightmap.align import (
    align_generated,
    measure_registration,
    punch_void,
    resize_to_source,
)
from tools.painted_map_pipeline.heightmap.run_chunk import run_heightmap_chunk
from tools.painted_map_pipeline.image_client import output_matches_source_size


def _box_pattern(w=64, h=64, x0=12, y0=16, x1=40, y1=44, value=220):
    arr = np.zeros((h, w), dtype=np.uint8)
    arr[y0:y1, x0:x1] = value
    return Image.fromarray(arr, mode="L")


def test_resize_to_source_uses_source_size():
    gen = _box_pattern(80, 50)
    aligned = resize_to_source(gen, (40, 25))
    assert aligned.size == (40, 25)
    assert aligned.mode == "L"


def test_measure_registration_recovers_known_shift():
    base = _box_pattern()
    shifted = Image.fromarray(np.roll(np.array(base), (3, 5), axis=(0, 1)), mode="L")
    qc = measure_registration(base, shifted, max_shift_px=16, min_response=0.01)
    assert qc["ok"]
    assert qc["dx"] == 5
    assert qc["dy"] == 3
    assert qc["response"] >= 0.01


def test_measure_registration_fails_large_shift():
    base = _box_pattern()
    shifted = Image.fromarray(np.roll(np.array(base), (0, 12), axis=(0, 1)), mode="L")
    qc = measure_registration(base, shifted, max_shift_px=8, min_response=0.0)
    assert not qc["ok"]
    assert abs(qc["dx"]) > 8


def test_punch_void_only_affects_preview_copy(tmp_path: Path):
    src = np.zeros((16, 16, 4), dtype=np.uint8)
    src[:, 8:, :] = 200
    src[:, 8:, 3] = 255
    source = Image.fromarray(src, mode="RGBA")
    height = Image.fromarray(np.full((16, 16), 180, dtype=np.uint8), mode="L")
    punched = punch_void(height, source)
    assert punched.getpixel((2, 8)) == 0
    assert punched.getpixel((12, 8)) == 180
    assert height.getpixel((2, 8)) == 180


def test_align_generated_writes_unpunched_height(tmp_path: Path):
    src = np.zeros((16, 20, 4), dtype=np.uint8)
    src[:, 10:, :] = 180
    src[:, 10:, 3] = 255
    source_path = tmp_path / "source.png"
    Image.fromarray(src, mode="RGBA").save(source_path)
    gen_path = tmp_path / "raw.png"
    Image.fromarray(np.full((8, 10), 90, dtype=np.uint8), mode="L").save(gen_path)
    height_out = tmp_path / "heightmap.png"
    preview_out = tmp_path / "preview.png"
    qc = align_generated(
        gen_path,
        source_path,
        height_out=height_out,
        preview_out=preview_out,
        max_shift_px=16,
        min_response=0.0,
    )
    assert height_out.exists()
    assert preview_out.exists()
    aligned = Image.open(height_out)
    assert aligned.size == (20, 16)
    assert aligned.getpixel((2, 8)) == 90
    aligned.close()
    assert qc["source_size"] == [20, 16]


def test_run_chunk_copy_provider_writes_qc(tmp_path: Path):
    import json

    chunk_dir = tmp_path / "chunk_99_99"
    chunk_dir.mkdir()
    src = np.zeros((32, 48, 4), dtype=np.uint8)
    src[:, :, 3] = 255
    src[8:20, 10:22, :3] = 200
    src[18:28, 24:40, :3] = 90
    source_path = chunk_dir / "source.png"
    Image.fromarray(src, mode="RGBA").save(source_path)
    manifest = {
        "chunks": [
            {
                "chunk_id": "chunk_99_99",
                "painted_image": str(source_path),
            }
        ]
    }
    manifest_path = tmp_path / "insert_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    config = {
        "provider": "copy",
        "preserve_existing": False,
        "qc_max_shift_px": 8,
        "qc_min_response": 0.0,
        "prompt": "unused for copy",
    }
    result = run_heightmap_chunk(
        chunk_id="chunk_99_99",
        manifest_path=manifest_path,
        config=config,
        repo=tmp_path,
        preserve_existing=False,
    )
    assert result["qc"]["ok"]
    assert result["qc"]["dx"] == 0
    assert result["qc"]["dy"] == 0
    assert (chunk_dir / "heightmap.png").exists()
    assert (chunk_dir / "heightmap_result.json").exists()


def test_output_matches_source_size(tmp_path: Path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("L", (12, 8), 1).save(a)
    Image.new("L", (12, 8), 2).save(b)
    assert output_matches_source_size(a, b)
    Image.new("L", (10, 8), 2).save(b)
    assert not output_matches_source_size(a, b)
    assert not output_matches_source_size(tmp_path / "missing.png", a)
