from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .config import load_config
from .coordinates import ScaledSpace, build_transform
from .masks import compute_overlap, overlap_on_canvas, pending_mask
from .models import LevelState
from .package_builder import level_paths
from .plan_loader import load_level_plan
from .state_store import append_event, atomic_write_json, read_json, sha256_file, utc_now

Image.MAX_IMAGE_PIXELS = None


def _load_context(root: Path):
    config = load_config(root / "config.resolved.json")
    run = read_json(root / "run.json")
    levels = load_level_plan(config.level_plan, tuple(run["world_size"]))
    scaled = ScaledSpace(config.scale)
    canvas_size = tuple(int(value) for value in run["canvas_size"])
    transforms = {
        level_id: build_transform(level, scaled, config.canvas, canvas_size)
        for level_id, level in levels.items()
    }
    return config, run, levels, scaled, canvas_size, transforms


def refresh_level(root: str | Path, level_id: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    config, run, levels, scaled, canvas_size, transforms = _load_context(root_path)
    level_id = level_id.zfill(2)
    if level_id not in levels:
        raise KeyError(f"unknown level: {level_id}")
    target_state = run["levels"][level_id]["state"]
    if target_state == LevelState.ACCEPTED.value:
        return {"level_id": level_id, "skipped": "accepted"}

    target = levels[level_id]
    target_paths = level_paths(root_path, level_id)
    target_manifest = read_json(target_paths["manifest"])
    with Image.open(target_paths["base_template"]) as opened:
        generation_input = opened.convert("RGBA")
    with Image.open(target_paths["generation_mask"]) as opened:
        generation_mask = opened.convert("L")
    locked_pixels = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    locked_mask_array = np.zeros((canvas_size[1], canvas_size[0]), dtype=bool)
    locked_sources: list[dict[str, Any]] = []

    accepted_neighbors = []
    for connection in target.connections:
        entry = run["levels"].get(connection.level_id, {})
        if connection.kind != "boat" and entry.get("state") == LevelState.ACCEPTED.value:
            accepted_neighbors.append(
                (int(entry.get("acceptance_index", 2**31)), connection.level_id)
            )
    accepted_neighbors.sort()

    overlaps_dir = target_paths["root"] / "masks" / "overlaps"
    overlaps_dir.mkdir(parents=True, exist_ok=True)
    for _, neighbor_id in accepted_neighbors:
        overlap = compute_overlap(target, levels[neighbor_id], scaled)
        if overlap is None:
            continue
        neighbor_paths = level_paths(root_path, neighbor_id)

        target_overlap = overlap_on_canvas(overlap, transforms[level_id])
        target_overlap.save(overlaps_dir / f"{neighbor_id}.png")

        source_overlaps_dir = neighbor_paths["root"] / "masks" / "overlaps"
        source_overlaps_dir.mkdir(parents=True, exist_ok=True)
        source_overlap = overlap_on_canvas(overlap, transforms[neighbor_id])
        source_overlap.save(source_overlaps_dir / f"{level_id}.png")

        overlap_array = np.asarray(target_overlap) > 0
        available = overlap_array & ~locked_mask_array
        if not np.any(available):
            continue

        accepted_path = neighbor_paths["root"] / "accepted" / "image.png"
        if not accepted_path.is_file():
            raise FileNotFoundError(f"accepted image missing for level {neighbor_id}: {accepted_path}")
        with Image.open(accepted_path) as opened:
            neighbor_image = opened.convert("RGBA")
        source_x, source_y = transforms[neighbor_id].global_to_local(
            overlap.global_box[0], overlap.global_box[1]
        )
        target_x, target_y = transforms[level_id].global_to_local(
            overlap.global_box[0], overlap.global_box[1]
        )
        source_region = neighbor_image.crop(
            (source_x, source_y, source_x + overlap.width, source_y + overlap.height)
        )
        available_region = available[
            target_y : target_y + overlap.height,
            target_x : target_x + overlap.width,
        ]
        paste_mask = Image.fromarray(available_region.astype(np.uint8) * 255, mode="L")
        locked_pixels.paste(source_region, (target_x, target_y), paste_mask)
        generation_input.paste(source_region, (target_x, target_y), paste_mask)
        locked_mask_array |= available
        locked_sources.append(
            {
                "neighbor_id": neighbor_id,
                "global_box": list(overlap.global_box),
                "pixel_count": int(np.count_nonzero(available)),
                "accepted_hash": sha256_file(accepted_path),
            }
        )

    locked_mask = Image.fromarray(locked_mask_array.astype(np.uint8) * 255, mode="L")
    blank = Image.new("RGBA", canvas_size, config.outside_color)
    generation_input = Image.composite(generation_input, blank, generation_mask)
    locked_pixels.save(target_paths["locked_pixels"])
    locked_mask.save(target_paths["locked_mask"])
    pending_mask(generation_mask, locked_mask).save(target_paths["pending_mask"])
    generation_input.save(target_paths["generation_input"])

    new_hash = sha256_file(target_paths["generation_input"])
    previous_hash = target_manifest.get("hashes", {}).get("generation_input")
    revision = int(target_manifest.get("context_revision", 0))
    if new_hash != previous_hash:
        revision += 1
    target_manifest.update(
        {
            "state": LevelState.READY.value,
            "locked_sources": locked_sources,
            "context_revision": revision,
            "updated_at": utc_now(),
        }
    )
    target_manifest.setdefault("hashes", {}).update(
        {
            "generation_input": new_hash,
            "locked_pixels": sha256_file(target_paths["locked_pixels"]),
            "locked_mask": sha256_file(target_paths["locked_mask"]),
        }
    )
    atomic_write_json(target_paths["manifest"], target_manifest)
    run["levels"][level_id].update(
        {
            "state": LevelState.READY.value,
            "context_revision": revision,
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(root_path / "run.json", run)
    append_event(
        root_path,
        "level_refreshed",
        level_id=level_id,
        context_revision=revision,
        locked_sources=[item["neighbor_id"] for item in locked_sources],
    )
    return {
        "level_id": level_id,
        "state": LevelState.READY.value,
        "context_revision": revision,
        "locked_sources": locked_sources,
    }


def refresh_neighbors(root: str | Path, accepted_level_id: str) -> list[dict[str, Any]]:
    root_path = Path(root).resolve()
    _, run, levels, _, _, _ = _load_context(root_path)
    level_id = accepted_level_id.zfill(2)
    results = []
    for connection in levels[level_id].connections:
        if connection.kind == "boat":
            continue
        if run["levels"][connection.level_id]["state"] != LevelState.ACCEPTED.value:
            results.append(refresh_level(root_path, connection.level_id))
    return results


def refresh_levels(root: str | Path, level_ids: list[str] | None = None) -> list[dict[str, Any]]:
    root_path = Path(root).resolve()
    _, run, _, _, _, _ = _load_context(root_path)
    selected = level_ids or sorted(run["levels"])
    return [refresh_level(root_path, level_id) for level_id in selected]
