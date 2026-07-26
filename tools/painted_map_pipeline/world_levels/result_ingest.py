from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from .config import load_config
from .land_fit import fit_generated_to_mask
from .models import LevelState
from .package_builder import level_paths
from .state_store import append_event, atomic_write_json, read_json, sha256_file, utc_now

Image.MAX_IMAGE_PIXELS = None


def _job_for_attempt(paths: dict[str, Path], attempt: int | None) -> tuple[Path, dict[str, Any]]:
    manifest = read_json(paths["manifest"])
    if attempt is None:
        latest = manifest.get("latest_job")
        if not latest:
            raise ValueError("level has no generation job")
        job_path = Path(latest)
    else:
        job_path = paths["root"] / "jobs" / f"attempt_{attempt:03d}" / "job.json"
    if not job_path.is_file():
        raise FileNotFoundError(f"generation job does not exist: {job_path}")
    return job_path, read_json(job_path)


def ingest_result(
    root: str | Path,
    level_id: str,
    image_path: str | Path,
    *,
    attempt: int | None = None,
    auto_accept: bool | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    config = load_config(root_path / "config.resolved.json")
    run = read_json(root_path / "run.json")
    level_id = level_id.zfill(2)
    paths = level_paths(root_path, level_id)
    level_manifest = read_json(paths["manifest"])
    job_path, job = _job_for_attempt(paths, attempt)
    if job["level_id"] != level_id:
        raise ValueError("job level ID does not match ingestion level")
    if int(job["context_revision"]) != int(level_manifest["context_revision"]):
        raise ValueError("job context is stale; refresh and create a new job")
    if sha256_file(job_path.parent / "input.png") != job["input_hash"]:
        raise ValueError("job input hash no longer matches its manifest")

    source_path = Path(image_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"generated image does not exist: {source_path}")
    with Image.open(source_path) as opened:
        generated = opened.convert("RGBA")
    expected_size = tuple(int(value) for value in job["canvas_size"])
    if generated.size != expected_size:
        raise ValueError(f"generated image is {generated.size}, expected {expected_size}")

    with Image.open(job_path.parent / "generation_mask.png") as opened:
        generation_mask = opened.convert("L")
    with Image.open(job_path.parent / "locked_overlap_mask.png") as opened:
        locked_mask = opened.convert("L")
    with Image.open(job_path.parent / "locked_overlap.png") as opened:
        locked_pixels = opened.convert("RGBA")

    # Warp generated land outline onto the template land silhouette.
    normalized = fit_generated_to_mask(
        generated,
        generation_mask,
        outside_color=config.outside_color,
    )
    normalized.paste(locked_pixels, (0, 0), locked_mask)
    attempt_number = int(job["attempt"])
    attempt_dir = paths["root"] / "attempts" / f"attempt_{attempt_number:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    raw_copy = attempt_dir / "generated.raw.png"
    normalized_path = attempt_dir / "normalized.png"
    if source_path != raw_copy:
        shutil.copy2(source_path, raw_copy)
    normalized.save(normalized_path)

    job.update(
        {
            "state": LevelState.GENERATED.value,
            "ingested_at": utc_now(),
            "source_image": str(source_path),
            "raw_hash": sha256_file(source_path),
            "normalized_path": str(normalized_path),
            "normalized_hash": sha256_file(normalized_path),
        }
    )
    atomic_write_json(job_path, job)
    level_manifest.update(
        {
            "state": LevelState.GENERATED.value,
            "latest_candidate": str(normalized_path),
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(paths["manifest"], level_manifest)
    run["levels"][level_id].update(
        {
            "state": LevelState.GENERATED.value,
            "latest_candidate": str(normalized_path),
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(root_path / "run.json", run)
    append_event(
        root_path,
        "result_ingested",
        level_id=level_id,
        attempt=attempt_number,
        normalized_hash=job["normalized_hash"],
    )
    should_accept = config.execution.approval_mode == "automatic" if auto_accept is None else auto_accept
    if should_accept:
        return accept_result(root_path, level_id, attempt=attempt_number)
    return {
        "level_id": level_id,
        "attempt": attempt_number,
        "state": LevelState.GENERATED.value,
        "normalized_path": str(normalized_path),
    }


def accept_result(
    root: str | Path,
    level_id: str,
    *,
    attempt: int | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    run = read_json(root_path / "run.json")
    level_id = level_id.zfill(2)
    paths = level_paths(root_path, level_id)
    manifest = read_json(paths["manifest"])
    job_path, job = _job_for_attempt(paths, attempt)
    if job.get("state") != LevelState.GENERATED.value:
        raise ValueError(f"job must be generated before acceptance, got {job.get('state')!r}")
    candidate = Path(job["normalized_path"])
    accepted_path = paths["root"] / "accepted" / "image.png"
    accepted_path.parent.mkdir(parents=True, exist_ok=True)
    if accepted_path.exists():
        accepted_hash = sha256_file(accepted_path)
        candidate_hash = sha256_file(candidate)
        if accepted_hash != candidate_hash:
            raise ValueError("accepted image already exists with different content")
    else:
        shutil.copy2(candidate, accepted_path)

    run["acceptance_counter"] = int(run.get("acceptance_counter", 0)) + 1
    acceptance_index = run["acceptance_counter"]
    job.update({"state": LevelState.ACCEPTED.value, "accepted_at": utc_now()})
    atomic_write_json(job_path, job)
    manifest.update(
        {
            "state": LevelState.ACCEPTED.value,
            "accepted_image": str(accepted_path),
            "accepted_hash": sha256_file(accepted_path),
            "accepted_attempt": int(job["attempt"]),
            "acceptance_index": acceptance_index,
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(paths["manifest"], manifest)
    run["levels"][level_id].update(
        {
            "state": LevelState.ACCEPTED.value,
            "accepted_image": str(accepted_path),
            "accepted_hash": manifest["accepted_hash"],
            "accepted_attempt": int(job["attempt"]),
            "acceptance_index": acceptance_index,
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(root_path / "run.json", run)
    append_event(
        root_path,
        "result_accepted",
        level_id=level_id,
        attempt=int(job["attempt"]),
        acceptance_index=acceptance_index,
    )

    from .package_refresher import refresh_neighbors

    refreshed = refresh_neighbors(root_path, level_id)
    return {
        "level_id": level_id,
        "attempt": int(job["attempt"]),
        "state": LevelState.ACCEPTED.value,
        "accepted_image": str(accepted_path),
        "refreshed_neighbors": refreshed,
    }
