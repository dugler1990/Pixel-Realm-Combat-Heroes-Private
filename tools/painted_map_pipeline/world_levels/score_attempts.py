"""Score every generation attempt for a level against its template silhouette.

Sampling variance in this pipeline is large enough to swamp prompt edits, so a single
attempt is not evidence. This reports the whole series plus a median so a change can be
judged on n draws rather than the most recent one.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from PIL import Image

from .job_builder import canvas_asset
from .land_fit import footprint_iou
from .package_builder import level_paths
from .state_store import read_json

Image.MAX_IMAGE_PIXELS = None


def _attempt_dirs(level_root: Path) -> list[Path]:
    jobs = level_root / "jobs"
    if not jobs.is_dir():
        return []
    return sorted(path for path in jobs.glob("attempt_*") if path.is_dir())


def score_level(root: str | Path, level_id: str) -> dict[str, Any]:
    root_path = Path(root).resolve()
    level_id = level_id.zfill(2)
    paths = level_paths(root_path, level_id)

    attempts: list[dict[str, Any]] = []
    for job_dir in _attempt_dirs(paths["root"]):
        generated = job_dir / "generated.png"
        entry: dict[str, Any] = {"attempt": int(job_dir.name.split("_")[-1])}

        job_path = job_dir / "job.json"
        renderer = read_json(job_path).get("renderer", "warp") if job_path.is_file() else "warp"
        entry["renderer"] = renderer

        result_path = job_dir / "generation_result.json"
        if result_path.is_file():
            result = read_json(result_path)
            for key in ("model", "seed", "generation_id", "returned_size", "size_mismatch", "error"):
                if result.get(key) is not None:
                    entry[key] = result[key]

        if not generated.is_file():
            entry["footprint_iou"] = None
            entry["note"] = "no generated.png"
            attempts.append(entry)
            continue

        if renderer != "warp":
            # There is no silhouette to score against: the frame renderer paints edge to edge
            # and the pipeline does the cutting. Reporting a number here would invite
            # comparing it against warp attempts, which measure a different thing.
            entry["footprint_iou"] = None
            entry["note"] = f"footprint IoU does not apply to the {renderer} renderer"
            attempts.append(entry)
            continue

        with Image.open(canvas_asset(job_dir, "generation_mask")) as opened:
            mask = opened.convert("L")
        with Image.open(generated) as opened:
            image = opened.convert("RGBA")
        if image.size != mask.size:
            entry["footprint_iou"] = None
            entry["note"] = f"size {image.size[0]}x{image.size[1]} != mask {mask.size[0]}x{mask.size[1]}"
            attempts.append(entry)
            continue
        entry["footprint_iou"] = round(footprint_iou(image, mask), 4)
        attempts.append(entry)

    scored = [item["footprint_iou"] for item in attempts if item.get("footprint_iou") is not None]
    summary: dict[str, Any] = {
        "level_id": level_id,
        "attempts": attempts,
        "scored_count": len(scored),
    }
    if scored:
        summary.update(
            {
                "median_footprint_iou": round(statistics.median(scored), 4),
                "best_footprint_iou": round(max(scored), 4),
                "worst_footprint_iou": round(min(scored), 4),
            }
        )
    if len(scored) < 4:
        summary["warning"] = (
            f"only {len(scored)} scored draw(s); sampling variance here exceeds typical "
            "prompt effects, so treat this as indicative only"
        )
    return summary


def score_levels(root: str | Path, level_ids: list[str]) -> list[dict[str, Any]]:
    return [score_level(root, level_id) for level_id in level_ids]
