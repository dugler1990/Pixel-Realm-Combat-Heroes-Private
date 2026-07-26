from __future__ import annotations

import argparse
import json
from pathlib import Path

from .batch_runner import parse_level_selector, run_batch
from .config import load_config
from .job_builder import create_job
from .models import LevelState
from .package_builder import prepare_run
from .package_refresher import refresh_levels
from .result_ingest import accept_result, ingest_result
from .state_store import read_json
from .validate_continuity import validate_run


def _selected_levels(
    run: dict,
    *,
    levels: str | None,
    region: str | None,
    state: str | None,
) -> list[str]:
    available = sorted(run["levels"])
    if levels:
        return parse_level_selector(levels, available)
    if region:
        return [
            level_id
            for level_id in available
            if str(run["levels"][level_id].get("region", "")).casefold() == region.casefold()
        ]
    if state:
        return [level_id for level_id in available if run["levels"][level_id].get("state") == state]
    return available


def _print(value) -> None:
    print(json.dumps(value, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and generate coordinate-locked irregular world levels.")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="Validate a config and prepare every level package.")
    prepare.add_argument("config", help="Path to world-level JSON config.")

    refresh = commands.add_parser("refresh", help="Rebuild AI inputs from accepted neighbor pixels.")
    refresh.add_argument("root", help="Prepared run root.")
    refresh.add_argument("--levels", help="Level selector, for example 01-05 or 01,04,06.")

    job = commands.add_parser("job", help="Refresh a level and snapshot an immutable generation job.")
    job.add_argument("root")
    job.add_argument("--level", required=True)

    ingest = commands.add_parser("ingest", help="Normalize a generated image for a prepared job.")
    ingest.add_argument("root")
    ingest.add_argument("--level", required=True)
    ingest.add_argument("--image", required=True)
    ingest.add_argument("--attempt", type=int)
    ingest.add_argument("--accept", action="store_true", help="Accept immediately after validation.")

    accept = commands.add_parser("accept", help="Accept a validated candidate and refresh its neighbors.")
    accept.add_argument("root")
    accept.add_argument("--level", required=True)
    accept.add_argument("--attempt", type=int)

    run_command = commands.add_parser("run", help="Run a resumable generation batch.")
    run_command.add_argument("root")
    run_command.add_argument("--levels", help="Level selector, for example 01-05 or 01,04,06.")
    run_command.add_argument("--region")
    run_command.add_argument("--state")

    resume = commands.add_parser("resume", help="Continue all prepared, ready, or failed levels.")
    resume.add_argument("root")

    status = commands.add_parser("status", help="Show run and level states.")
    status.add_argument("root")

    validate = commands.add_parser("validate", help="Validate packages and accepted overlaps.")
    validate.add_argument("root")
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        _print(prepare_run(load_config(args.config)))
        return

    root = Path(args.root).expanduser().resolve()
    run = read_json(root / "run.json")
    if args.command == "refresh":
        ids = parse_level_selector(args.levels, run["levels"]) if args.levels else None
        _print(refresh_levels(root, ids))
    elif args.command == "job":
        from .package_refresher import refresh_level

        refresh_level(root, args.level)
        job = create_job(root, args.level)
        _print({"level_id": job.level_id, "attempt": job.attempt, "directory": str(job.directory)})
    elif args.command == "ingest":
        _print(
            ingest_result(
                root,
                args.level,
                args.image,
                attempt=args.attempt,
                auto_accept=True if args.accept else None,
            )
        )
    elif args.command == "accept":
        _print(accept_result(root, args.level, attempt=args.attempt))
    elif args.command == "run":
        selected = _selected_levels(run, levels=args.levels, region=args.region, state=args.state)
        _print(run_batch(root, selected))
    elif args.command == "resume":
        resumable = {
            LevelState.PREPARED.value,
            LevelState.READY.value,
            LevelState.FAILED.value,
        }
        selected = [
            level_id
            for level_id in sorted(run["levels"])
            if run["levels"][level_id]["state"] in resumable
        ]
        _print(run_batch(root, selected))
    elif args.command == "status":
        _print(
            {
                "root": str(root),
                "config_hash": run["config_hash"],
                "levels": {
                    level_id: {
                        key: value
                        for key, value in entry.items()
                        if key in {"name", "region", "state", "attempt_count", "context_revision", "error"}
                    }
                    for level_id, entry in run["levels"].items()
                },
            }
        )
    elif args.command == "validate":
        _print(validate_run(root))


if __name__ == "__main__":
    main()
