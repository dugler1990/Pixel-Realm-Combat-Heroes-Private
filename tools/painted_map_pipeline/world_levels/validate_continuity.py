from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .config import load_config
from .coordinates import ScaledSpace, build_transform
from .masks import compute_overlap
from .models import LevelState
from .package_builder import level_paths
from .plan_loader import load_level_plan
from .state_store import atomic_write_json, read_json, sha256_file, utc_now


def validate_run(root: str | Path) -> dict[str, Any]:
    root_path = Path(root).resolve()
    config = load_config(root_path / "config.resolved.json")
    run = read_json(root_path / "run.json")
    levels = load_level_plan(config.level_plan, tuple(run["world_size"]))
    scaled = ScaledSpace(config.scale)
    canvas_size = tuple(run["canvas_size"])
    transforms = {
        level_id: build_transform(level, scaled, config.canvas, canvas_size)
        for level_id, level in levels.items()
    }
    errors: list[str] = []
    pairs: list[dict[str, Any]] = []
    for level_id, level in levels.items():
        paths = level_paths(root_path, level_id)
        for required in ("manifest", "dense_template", "generation_mask", "core_mask"):
            if not paths[required].is_file():
                errors.append(f"level {level_id}: missing {required}")
        for connection in level.connections:
            neighbor_id = connection.level_id
            if connection.kind == "boat" or level_id >= neighbor_id:
                continue
            if (
                run["levels"][level_id]["state"] != LevelState.ACCEPTED.value
                or run["levels"][neighbor_id]["state"] != LevelState.ACCEPTED.value
            ):
                continue
            overlap = compute_overlap(level, levels[neighbor_id], scaled)
            if overlap is None:
                errors.append(f"accepted land pair {level_id}-{neighbor_id}: missing overlap")
                continue
            first_path = level_paths(root_path, level_id)["root"] / "accepted" / "image.png"
            second_path = level_paths(root_path, neighbor_id)["root"] / "accepted" / "image.png"
            with Image.open(first_path) as opened:
                first = opened.convert("RGBA")
            with Image.open(second_path) as opened:
                second = opened.convert("RGBA")
            first_x, first_y = transforms[level_id].global_to_local(*overlap.global_box[:2])
            second_x, second_y = transforms[neighbor_id].global_to_local(*overlap.global_box[:2])
            first_array = np.asarray(
                first.crop((first_x, first_y, first_x + overlap.width, first_y + overlap.height))
            )
            second_array = np.asarray(
                second.crop((second_x, second_y, second_x + overlap.width, second_y + overlap.height))
            )
            active = overlap.pixels > 0
            difference = np.any(first_array != second_array, axis=2) & active
            differing = int(np.count_nonzero(difference))
            pairs.append(
                {
                    "levels": [level_id, neighbor_id],
                    "overlap_pixels": int(np.count_nonzero(active)),
                    "differing_pixels": differing,
                    "first_hash": sha256_file(first_path),
                    "second_hash": sha256_file(second_path),
                }
            )
            if differing:
                errors.append(f"accepted pair {level_id}-{neighbor_id}: {differing} overlap pixels differ")
    report = {
        "valid": not errors,
        "checked_at": utc_now(),
        "errors": errors,
        "accepted_pairs": pairs,
    }
    atomic_write_json(root_path / "continuity_report.json", report)
    return report
