from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .config import load_config
from .generation_backend import make_generation_backend
from .job_builder import create_job
from .models import LevelState
from .package_refresher import refresh_level
from .result_ingest import ingest_result
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
) -> dict:
    root_path = Path(root).resolve()
    config = load_config(root_path / "config.resolved.json")
    backend = make_generation_backend(config.generation)
    summary: dict = {"selected": level_ids, "results": [], "status": "finished"}
    append_event(root_path, "batch_started", selected=level_ids)
    for level_id in level_ids:
        run = read_json(root_path / "run.json")
        if run["levels"][level_id]["state"] == LevelState.ACCEPTED.value:
            summary["results"].append({"level_id": level_id, "skipped": "accepted"})
            continue
        refresh_level(root_path, level_id)
        job = create_job(root_path, level_id)
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

        result = ingest_result(root_path, level_id, generated_path, attempt=job.attempt)
        summary["results"].append(result)
        if result["state"] != LevelState.ACCEPTED.value:
            summary["status"] = "waiting_for_approval"
            break
    append_event(root_path, "batch_finished", status=summary["status"])
    return summary
