from __future__ import annotations

import shutil
from pathlib import Path

from .config import load_config
from .models import GenerationJob, LevelState
from .package_builder import level_paths
from .state_store import append_event, atomic_write_json, read_json, sha256_file, utc_now


def _prompt(level_manifest: dict, style_prompt: str) -> str:
    locked = [item["neighbor_id"] for item in level_manifest.get("locked_sources", [])]
    width, height = level_manifest["canvas_size"]
    lines = [
        f"Render level {level_manifest['level_id']}: {level_manifest['name']} ({level_manifest['region']}).",
        f"Return exactly {width}x{height} pixels.",
        "",
        "Context images (use each file for the role named below):",
        "1. input.png — exact composition, scale, coastline, terrain placement, and boundary authority.",
        "2. locked_overlap.png — already-painted neighbor padding only; final art for continuity and style.",
        "3. generation_mask.png — exact land silhouette to fill; leave exterior blank.",
        "4. pending_mask.png — area still to generate (land minus locked padding).",
        "5. locator.png — map position only; do not invent composition or style from it.",
        "",
        "Paint only inside the land / generation area. Leave the blank exterior blank.",
        "Preserve the exact terrain structures and proportions shown by input.png / generation_mask.png.",
        "Keep lighting diffuse and shadow-neutral: local form shading is allowed, directional cast shadows are not.",
        "Do not add labels, UI, borders, map symbols, characters, or a visible grid.",
    ]
    if locked:
        locked_text = ", ".join(locked)
        lines.extend(
            [
                f"Accepted neighbor padding in locked_overlap.png / input.png comes from level(s): {locked_text}.",
                "Treat locked_overlap.png as final art — do not restyle, recolor, or reinterpret it.",
                "Generate only the unfinished land (pending_mask.png) as a continuous extension of that padding,",
                "as if the whole level were painted in one pass.",
                "Terrain may change with geography, but it must stay in the same visual language as locked_overlap.png",
                "— not a different style that only meets it at the edge.",
                "Region flavor (secondary to the padding):",
                style_prompt,
            ]
        )
    else:
        lines.extend(
            [
                "No neighbor padding is present (locked_overlap.png is empty). This is a seed level.",
                "Establish the level's look from the style guidance below and input.png / generation_mask.png.",
                style_prompt,
            ]
        )
    return "\n".join(lines).strip() + "\n"


def create_job(root: str | Path, level_id: str) -> GenerationJob:
    root_path = Path(root).resolve()
    config = load_config(root_path / "config.resolved.json")
    run = read_json(root_path / "run.json")
    level_id = level_id.zfill(2)
    state = run["levels"][level_id]["state"]
    if state not in {LevelState.PREPARED.value, LevelState.READY.value, LevelState.FAILED.value}:
        raise ValueError(f"level {level_id} cannot create a job from state {state!r}")
    paths = level_paths(root_path, level_id)
    manifest = read_json(paths["manifest"])
    attempt = int(manifest.get("attempt_count", 0)) + 1
    job_dir = paths["root"] / "jobs" / f"attempt_{attempt:03d}"
    if job_dir.exists():
        raise FileExistsError(f"job attempt already exists: {job_dir}")
    job_dir.mkdir(parents=True)

    copies = {
        "input.png": paths["generation_input"],
        "generation_mask.png": paths["generation_mask"],
        "pending_mask.png": paths["pending_mask"],
        "locked_overlap.png": paths["locked_pixels"],
        "locked_overlap_mask.png": paths["locked_mask"],
        "locator.png": paths["locator"],
    }
    for name, source in copies.items():
        shutil.copy2(source, job_dir / name)
    prompt_path = job_dir / "prompt.txt"
    prompt_path.write_text(_prompt(manifest, config.style_prompt), encoding="utf-8")
    job_manifest = {
        "schema_version": 1,
        "level_id": level_id,
        "attempt": attempt,
        "state": LevelState.READY.value,
        "created_at": utc_now(),
        "context_revision": manifest["context_revision"],
        "canvas_size": manifest["canvas_size"],
        "input_hash": sha256_file(job_dir / "input.png"),
        "generation_mask_hash": sha256_file(job_dir / "generation_mask.png"),
        "locked_mask_hash": sha256_file(job_dir / "locked_overlap_mask.png"),
        "locked_pixels_hash": sha256_file(job_dir / "locked_overlap.png"),
        "neighbor_sources": manifest.get("locked_sources", []),
        "output_path": str(job_dir / "generated.png"),
    }
    atomic_write_json(job_dir / "job.json", job_manifest)
    manifest.update(
        {
            "attempt_count": attempt,
            "latest_job": str(job_dir / "job.json"),
            "state": LevelState.READY.value,
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(paths["manifest"], manifest)
    run["levels"][level_id].update(
        {
            "state": LevelState.READY.value,
            "attempt_count": attempt,
            "latest_job": str(job_dir / "job.json"),
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(root_path / "run.json", run)
    append_event(root_path, "job_created", level_id=level_id, attempt=attempt)
    return GenerationJob(
        level_id=level_id,
        attempt=attempt,
        directory=job_dir,
        input_path=job_dir / "input.png",
        prompt_path=prompt_path,
        output_path=job_dir / "generated.png",
        manifest_path=job_dir / "job.json",
    )
