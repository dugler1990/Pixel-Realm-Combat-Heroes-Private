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
from .plan_loader import load_level_plan
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


def _review_links(label: str, paths) -> None:
    """Print absolute paths to the images worth checking. VS Code's terminal turns
    absolute paths into clickable links, so this is how each command surfaces its output
    art for review."""
    existing = []
    for path in paths:
        if not path:
            continue
        resolved = Path(path)
        if resolved.exists():
            existing.append(resolved.resolve())
    if existing:
        print(f"\n{label}:")
        for resolved in existing:
            print(f"  {resolved}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and generate coordinate-locked irregular world levels.")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="Validate a config and prepare every level package.")
    prepare.add_argument("config", help="Path to world-level JSON config.")

    split = commands.add_parser(
        "split",
        help="Divide chunks into sub-levels, writing a nested run per chunk under <output_root>/subs/.",
    )
    split.add_argument("config", help="Path to the parent world-level JSON config (with a `split` block).")
    split.add_argument("--chunks", help="Chunk selector, for example 04 or 04,07 or 04-07.")

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
    run_command.add_argument(
        "--prompt-file",
        help="Send this file's contents as the prompt instead of the generated one.",
    )
    run_command.add_argument(
        "--refine",
        action="store_true",
        help="Second pass over accepted art: start from the level's own image and align it "
        "to its padding, instead of regenerating from the world-map template.",
    )

    resume = commands.add_parser("resume", help="Continue all prepared, ready, or failed levels.")
    resume.add_argument("root")

    status = commands.add_parser("status", help="Show run and level states.")
    status.add_argument("root")

    validate = commands.add_parser("validate", help="Validate packages and accepted overlaps.")
    validate.add_argument("root")

    score = commands.add_parser(
        "score",
        help="Report raw footprint IoU per attempt (pre-warp) so draws can be compared.",
    )
    score.add_argument("root")
    score.add_argument("--levels", help="Level selector, for example 01-05 or 01,04,06.")
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "prepare":
        config = load_config(args.config)
        _print(prepare_run(config))
        _review_links("check the labelled overlay", [config.output_root / "plan_validation_overlay.png"])
        return
    if args.command == "split":
        from .splitter import split_run

        config = load_config(args.config)
        if args.chunks:
            available = sorted(load_level_plan(config.level_plan))
            chunk_ids = parse_level_selector(args.chunks, available)
        else:
            chunk_ids = None
        result = split_run(config, chunk_ids)
        _print(result)
        overlays = [item.get("division_overlay") for item in result.get("results", [])]
        _review_links("check the split (chunk art with sub-level boundaries + names)", overlays)
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
        result = ingest_result(
            root,
            args.level,
            args.image,
            attempt=args.attempt,
            auto_accept=True if args.accept else None,
        )
        _print(result)
        _review_links("images", [result.get("normalized_path"), result.get("accepted_image")])
    elif args.command == "accept":
        result = accept_result(root, args.level, attempt=args.attempt)
        _print(result)
        _review_links("images", [result.get("accepted_image")])
    elif args.command == "run":
        selected = _selected_levels(run, levels=args.levels, region=args.region, state=args.state)
        summary = run_batch(root, selected, args.prompt_file, refine=args.refine)
        _print(summary)
        images = []
        for item in summary.get("results", []):
            images += [item.get("normalized_path"), item.get("accepted_image"), item.get("source_image")]
        _review_links("images", images)
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
    elif args.command == "score":
        from .score_attempts import score_levels

        ids = parse_level_selector(args.levels, run["levels"]) if args.levels else sorted(run["levels"])
        _print(score_levels(root, ids))


if __name__ == "__main__":
    main()
