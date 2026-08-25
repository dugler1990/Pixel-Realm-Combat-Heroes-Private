from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .config import load_config
from .generation_backend import make_generation_backend
from .job_builder import create_job
from .models import LevelState
from .package_refresher import refresh_level
from .result_ingest import FootprintRejected, ingest_result
from .state_store import append_event, read_json, update_level_state


def parse_level_selector(selector: str, available: Iterable[str]) -> list[str]:
    available_ids = set(available)
    selected: list[str] = []
    for token in filter(None, (part.strip() for part in selector.split(","))):
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", token)
        if match:
            start, finish = int(match.group(1)), int(match.group(2))
            step = 1 if finish >= start else -1
            selected.extend(f"{value:02d}" for value in range(start, finish + step, step))
        elif token.isdigit():
            selected.append(token.zfill(2))
        else:
            raise ValueError(f"invalid level selector token: {token!r}")
    unknown = [level_id for level_id in selected if level_id not in available_ids]
    if unknown:
        raise ValueError(f"unknown selected levels: {', '.join(unknown)}")
    return list(dict.fromkeys(selected))


def run_batch(
    root: str | Path,
    level_ids: list[str],
    prompt_file: str | Path | None = None,
    refine: bool = False,
    feather: int = 0,
    retry_reason: str | None = None,
    retry_image: str | None = None,
    retry_note: str = "",
    fit_to_mask: bool = False,
    cut_to_mask: bool = False,
    padding: str = "all",
) -> dict:
    root_path = Path(root).resolve()
    config = load_config(root_path / "config.resolved.json")
    backend = make_generation_backend(config.generation)
    summary: dict = {"selected": level_ids, "results": [], "status": "finished"}
    append_event(root_path, "batch_started", selected=level_ids)
    for level_id in level_ids:
        run = read_json(root_path / "run.json")
        # A refine pass deliberately reruns finished levels, so accepted is its input
        # state rather than a reason to skip.
        if run["levels"][level_id]["state"] == LevelState.ACCEPTED.value and not refine:
            summary["results"].append({"level_id": level_id, "skipped": "accepted"})
            continue
        refresh_level(root_path, level_id, force=refine, refine=refine)
        job = create_job(
                root_path,
                level_id,
                prompt_file,
                refine=refine,
                retry_reason=retry_reason,
                retry_image=retry_image,
                retry_note=retry_note,
            )
        update_level_state(root_path, level_id, LevelState.GENERATING.value, attempt=job.attempt)

        generated_path = None
        last_error: Exception | None = None
        for retry in range(config.execution.retry_limit + 1):
            try:
                generated_path = backend.generate(job)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                append_event(
                    root_path,
                    "generation_retry",
                    level_id=level_id,
                    attempt=job.attempt,
                    retry=retry,
                    error=str(exc),
                )
        if last_error is not None:
            update_level_state(
                root_path,
                level_id,
                LevelState.FAILED.value,
                attempt=job.attempt,
                error=str(last_error),
            )
            summary["results"].append({"level_id": level_id, "state": "failed", "error": str(last_error)})
            if config.execution.stop_on_failure:
                summary["status"] = "failed"
                break
            continue

        if generated_path is None:
            update_level_state(root_path, level_id, LevelState.READY.value, attempt=job.attempt)
            summary["results"].append(
                {
                    "level_id": level_id,
                    "state": "ready",
                    "job": str(job.directory),
                    "awaiting_external_image": True,
                }
            )
            summary["status"] = "waiting_for_image"
            break

        try:
            result = ingest_result(
                root_path,
                level_id,
                generated_path,
                attempt=job.attempt,
                feather=feather,
                fit_to_mask=fit_to_mask,
                cut_to_mask=cut_to_mask,
                padding=padding,
            )
        except FootprintRejected as exc:
            # A reframed draw is a failed draw, not a crash: fail the level the same way a
            # generation error would, so the batch stays resumable.
            update_level_state(
                root_path,
                level_id,
                LevelState.FAILED.value,
                attempt=job.attempt,
                error=str(exc),
            )
            summary["results"].append(
                {
                    "level_id": level_id,
                    "state": "failed",
                    "reason": "footprint_rejected",
                    "footprint_iou": exc.footprint_iou,
                    "threshold": exc.threshold,
                    "job": str(job.directory),
                }
            )
            if config.execution.stop_on_failure:
                summary["status"] = "failed"
                break
            continue

        summary["results"].append(result)
        if result["state"] != LevelState.ACCEPTED.value:
            summary["status"] = "waiting_for_approval"
            break
    append_event(root_path, "batch_finished", status=summary["status"])
    return summary
