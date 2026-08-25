from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .config import load_config
from .coordinates import ScaledSpace, build_transform
from .masks import shared_strip
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
            # Two neighbours no longer agree across the whole overlap, and should not: each
            # owns its own core there and paints it itself. What must agree is only what one
            # actually inherited from the other -- its shared strip, and only where its locked
            # mask says those pixels were taken. Checked in both directions, since which level
            # was accepted first decides who inherited from whom.
            checked = False
            for receiver, giver in ((level_id, neighbor_id), (neighbor_id, level_id)):
                strip = shared_strip(levels[receiver], levels[giver], scaled)
                if strip is None:
                    continue
                receiver_path = level_paths(root_path, receiver)["root"] / "accepted" / "image.png"
                giver_path = level_paths(root_path, giver)["root"] / "accepted" / "image.png"
                locked_path = level_paths(root_path, receiver)["locked_mask"]
                if not locked_path.is_file():
                    continue
                with Image.open(receiver_path) as opened:
                    receiver_image = opened.convert("RGBA")
                with Image.open(giver_path) as opened:
                    giver_image = opened.convert("RGBA")
                with Image.open(locked_path) as opened:
                    locked = np.asarray(opened.convert("L")) > 0
                rx, ry = transforms[receiver].global_to_local(*strip.global_box[:2])
                gx, gy = transforms[giver].global_to_local(*strip.global_box[:2])
                receiver_array = np.asarray(
                    receiver_image.crop((rx, ry, rx + strip.width, ry + strip.height))
                )
                giver_array = np.asarray(
                    giver_image.crop((gx, gy, gx + strip.width, gy + strip.height))
                )
                active = (strip.pixels > 0) & locked[ry : ry + strip.height, rx : rx + strip.width]
                if not np.any(active):
                    continue
                checked = True
                difference = np.any(receiver_array != giver_array, axis=2) & active
                differing = int(np.count_nonzero(difference))
                pairs.append(
                    {
                        "levels": [receiver, giver],
                        "inherited_by": receiver,
                        "overlap_pixels": int(np.count_nonzero(active)),
                        "differing_pixels": differing,
                        "first_hash": sha256_file(receiver_path),
                        "second_hash": sha256_file(giver_path),
                    }
                )
                if differing:
                    errors.append(
                        f"accepted pair {receiver}-{giver}: {differing} inherited pixels differ"
                    )
            if not checked:
                continue
            differing = 0
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
