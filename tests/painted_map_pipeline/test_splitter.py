from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image

from tools.painted_map_pipeline.world_levels import region_proposer as rp
from tools.painted_map_pipeline.world_levels.config import load_config
from tools.painted_map_pipeline.world_levels.coordinates import ScaledSpace, resolve_canvas
from tools.painted_map_pipeline.world_levels.geometry import polygon_bbox
from tools.painted_map_pipeline.world_levels.masks import compute_overlap, rasterize_polygon
from tools.painted_map_pipeline.world_levels.models import SplitConfig
from tools.painted_map_pipeline.world_levels.plan_loader import load_level_plan
from tools.painted_map_pipeline.world_levels.region_proposer import ProposeRequest, ProposedRegion
from tools.painted_map_pipeline.world_levels.splitter import split_chunk, split_run

CSV_FIELDS = [
    "id",
    "name",
    "region",
    "crop_x_px",
    "crop_y_px",
    "crop_width_px",
    "crop_height_px",
    "overlap_buffer_px",
    "core_polygon_points_px",
    "generation_polygon_points_px",
    "connections",
]


def _single_chunk_config(tmp_path: Path) -> Path:
    """A world with one big chunk and a split block bucketing to 3 sub-levels."""
    world_path = tmp_path / "world.png"
    world = np.zeros((40, 60, 4), dtype=np.uint8)
    world[..., 3] = 255
    world[..., 0] = 120
    Image.fromarray(world, mode="RGBA").save(world_path)

    plan_path = tmp_path / "levels.csv"
    with plan_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerow(
            {
                "id": "01",
                "name": "Big Chunk",
                "region": "Test",
                "crop_x_px": 0,
                "crop_y_px": 0,
                "crop_width_px": 60,
                "crop_height_px": 40,
                "overlap_buffer_px": 2,
                "core_polygon_points_px": "5:5|54:5|54:34|5:34",
                "generation_polygon_points_px": "3:3|56:3|56:36|3:36",
                "connections": "",
            }
        )

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "world_map": str(world_path),
                "level_plan": str(plan_path),
                "output_root": str(tmp_path / "output"),
                "canvas": {"mode": "explicit", "width": 60, "height": 40, "placement": "center", "margin": 0},
                "scale": {"pixels_per_world_pixel": 1},
                "rendering": {"outside_color": [0, 0, 0, 255], "source_resampling": "nearest"},
                "execution": {"approval_mode": "manual"},
                "generation": {"provider": "copy"},
                "style_prompt": "Test.",
                "split": {
                    "buckets": [[1000, 2]],
                    "default_count": 3,
                    "overlap_buffer_px": 2,
                    "crop_margin_px": 1,
                    "proposer": {"provider": "grid"},
                },
            }
        ),
        encoding="utf-8",
    )
    return config_path


def _write_fake_chunk_art(output_root, chunk, size: tuple[int, int]) -> Path:
    """A stand-in accepted chunk image, so split_chunk (which sources from it) can run.
    Real chunk art is the chunk silhouette painted on black, so paint only the generation
    polygon non-black -- the splitter derives its frame from the non-black extent."""
    path = Path(output_root) / "levels" / chunk.level_id / "accepted" / "image.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    land = np.asarray(rasterize_polygon(size, chunk.generation_polygon)) > 0
    art = np.zeros((size[1], size[0], 4), dtype=np.uint8)
    art[..., 3] = 255
    art[land] = (60, 80, 60, 255)
    Image.fromarray(art, mode="RGBA").save(path)
    return path


def test_split_config_buckets_clamp():
    cfg = SplitConfig(buckets=((24000.0, 2), (40000.0, 3), (52000.0, 4), (62000.0, 5)), default_count=6)
    assert cfg.count_for_area(18300) == 2
    assert cfg.count_for_area(35800) == 3
    assert cfg.count_for_area(46850) == 4
    assert cfg.count_for_area(55400) == 5
    assert cfg.count_for_area(64500) == 6
    # clamp
    tight = SplitConfig(buckets=((100.0, 1),), default_count=99, min_sublevels=2, max_sublevels=6)
    assert tight.count_for_area(50) == 2  # 1 clamped up to min
    assert tight.count_for_area(500) == 6  # 99 clamped down to max


def test_split_run_emits_valid_nested_run(tmp_path: Path):
    config = load_config(_single_chunk_config(tmp_path))
    plan = load_level_plan(config.level_plan)
    canvas_size = resolve_canvas(config.canvas, plan, ScaledSpace(config.scale))
    _write_fake_chunk_art(config.output_root, plan["01"], canvas_size)
    result = split_run(config, ["01"])
    entry = result["results"][0]
    assert entry["requested_count"] == 3
    assert 2 <= entry["sub_level_count"] <= 6

    child_plan = Path(entry["child_plan"])
    assert child_plan.is_file()
    # The written plan passes the REAL loader: simple polygons, vertices in crop, symmetry.
    levels = load_level_plan(child_plan)
    assert len(levels) == entry["sub_level_count"]

    # Adjacency is real: at least one connected pair, verified via the canonical overlap.
    scaled = ScaledSpace(config.scale)
    ids = list(levels)
    overlaps = [
        compute_overlap(levels[a], levels[b], scaled) is not None
        for i, a in enumerate(ids)
        for b in ids[i + 1 :]
    ]
    assert any(overlaps)
    assert any(spec.connections for spec in levels.values())

    # The child config is a normal, loadable world-level config with no further split.
    child_config = load_config(entry["child_config"])
    assert Path(child_config.level_plan) == child_plan.resolve()
    assert child_config.split is None

    manifest = json.loads((child_plan.parent / "split_manifest.json").read_text(encoding="utf-8"))
    assert all(sub["tag"] == "flat" for sub in manifest["sub_levels"])


class _StubProposer:
    """Splits the request's chunk polygon into left/right halves with distinct tags,
    to prove tag propagation regardless of coordinate frame."""

    def propose(self, request):
        left, top, right, bottom = polygon_bbox(request.chunk_polygon)
        mid = (left + right) // 2
        return [
            ProposedRegion(polygon=((left, top), (mid, top), (mid, bottom), (left, bottom)),
                           tag="flat", name="Left"),
            ProposedRegion(polygon=((mid, top), (right, top), (right, bottom), (mid, bottom)),
                           tag="mountain", name="Right"),
        ]


def test_split_chunk_propagates_mountain_tag(tmp_path: Path):
    config = load_config(_single_chunk_config(tmp_path))
    levels = load_level_plan(config.level_plan)
    chunk = levels["01"]
    parent_scaled = ScaledSpace(config.scale)
    canvas_size = resolve_canvas(config.canvas, levels, parent_scaled)
    _write_fake_chunk_art(config.output_root, chunk, canvas_size)
    manifest = split_chunk(config, chunk, _StubProposer(), canvas_size)

    tags = [sub["tag"] for sub in manifest["sub_levels"]]
    assert tags == ["flat", "mountain"]

    # The tag column is written and the two halves are adjacent (connected).
    rows = list(csv.DictReader(Path(manifest["child_plan"]).open(encoding="utf-8")))
    assert {row["tag"] for row in rows} == {"flat", "mountain"}
    levels = load_level_plan(manifest["child_plan"])
    assert all(spec.connections for spec in levels.values())


def test_image_division_proposer_traces_colors(monkeypatch, tmp_path: Path):
    """The image proposer repaints the chunk into flat colors, then TRACES those colors
    into world-space polygons. The paint (edit_image) call is stubbed with a synthetic
    left-red / right-green image, so no network."""
    import numpy as np
    from PIL import Image

    source = tmp_path / "src.png"
    Image.new("RGB", (400, 200), (20, 20, 20)).save(source)

    def fake_edit_image(*, prompt, input_images, mask, output_path, width, height, config):
        painted = np.zeros((height, width, 3), dtype=np.uint8)
        painted[:, : width // 2] = (220, 50, 50)   # red  (region 1) on the left
        painted[:, width // 2 :] = (50, 200, 80)    # green (region 2) on the right
        Image.fromarray(painted).save(output_path)
        return {}

    monkeypatch.setattr(rp, "edit_image", fake_edit_image)
    proposer = rp.make_region_proposer({"provider": "openai", "model": "gpt-image-2"})

    request = ProposeRequest(
        chunk_id="19",
        chunk_polygon=((0, 0), (200, 0), (200, 100), (0, 100)),
        chunk_art=source,
        n=2,
        criteria="divide it",
        world_bbox=(0, 0, 200, 100),  # left half -> x<100, right half -> x>100
    )
    regions = proposer.propose(request)
    assert len(regions) == 2
    centroid_x = sorted(sum(p[0] for p in r.polygon) / len(r.polygon) for r in regions)
    assert centroid_x[0] < 100 < centroid_x[1]  # colors traced to the correct world halves
    assert {r.name for r in regions} == {"Region 1", "Region 2"}
    assert all(r.tag == "flat" for r in regions)
