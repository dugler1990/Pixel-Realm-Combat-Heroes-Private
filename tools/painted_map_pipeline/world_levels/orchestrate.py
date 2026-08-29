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
    ingest.add_argument("--feather", type=int, default=0, help="Fade the padding in over N px at the join.")
    ingest.add_argument("--fit-to-mask", action="store_true", help="Force the return's outline onto the mask by warping it. Off by default: the warp shifts every feature in the picture, including the padding other levels inherit. Prefer retrying a low-scoring draw.")
    ingest.add_argument("--cut-to-mask", action="store_true", help="Trim whatever spilled past the polygon, without warping. Use when the check reports cut_iou near 1 and the raw IoU below it: the miss is then a fringe at the edge, not a misplaced render. Cannot fill a shortfall.")
    ingest.add_argument("--padding", choices=["all", "none"], default="all", help="Paste the neighbours' padding strips, or not. 'none' re-places the same generation with the model's own art left everywhere, so a bad join can be told apart from a bad generation. Costs no API call.")

    accept = commands.add_parser("accept", help="Accept a validated candidate and refresh its neighbors.")
    accept.add_argument("root")
    accept.add_argument("--level", required=True)
    accept.add_argument("--attempt", type=int)

    unaccept = commands.add_parser(
        "unaccept",
        help="Reopen an accepted level for another attempt, and rebuild its neighbours "
        "so its pixels stop padding them.",
    )
    unaccept.add_argument("root")
    unaccept.add_argument("--level", required=True)

    compose = commands.add_parser(
        "compose",
        help="Custom creative re-composition of a sub-level's accepted art (add features); "
        "keeps numbered attempts.",
    )
    compose.add_argument("root")
    compose.add_argument("--level", required=True)
    compose.add_argument("--prompt", help="Prompt file for the composition (required unless --accept).")
    compose.add_argument(
        "--accept",
        type=int,
        metavar="ATTEMPT",
        help="Promote this attempt to composed.png instead of generating.",
    )
    compose.add_argument(
        "--player-px",
        type=int,
        help="Stamp player-sized figures on the input as a visible scale anchor (px tall).",
    )
    compose.add_argument("--player-sprite", default="image_assets/barbwalk/0.png")
    compose.add_argument("--player-count", type=int, default=6)

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
        "--feather",
        type=int,
        default=0,
        help="Fade the padding into the new art over N px at their join, instead of a hard "
             "paste (the shared edge stays byte-identical). Try 24.",
    )
    run_command.add_argument(
        "--retry-image",
        help="Attach this image to the retry as evidence, described by --retry-note.",
    )
    run_command.add_argument(
        "--retry-note",
        default="",
        help="What the attached image shows and what to do about it.",
    )
    run_command.add_argument("--fit-to-mask", action="store_true", help="Force the return's outline onto the mask by warping it. Off by default: the warp shifts every feature in the picture, including the padding other levels inherit. Prefer retrying a low-scoring draw.")
    run_command.add_argument("--cut-to-mask", action="store_true", help="Trim whatever spilled past the polygon, without warping. Use when the check reports cut_iou near 1 and the raw IoU below it: the miss is then a fringe at the edge, not a misplaced render. Cannot fill a shortfall.")
    run_command.add_argument("--padding", choices=["all", "none"], default="all", help="Paste the neighbours' padding strips, or not. 'none' re-places the same generation with the model's own art left everywhere, so a bad join can be told apart from a bad generation. Costs no API call.")
    run_command.add_argument(
        "--retry-reason",
        nargs="?",
        const="",
        help="Send the rejected previous attempt back with the automatic check failures, "
        "plus this sentence if one is given.",
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

    check = commands.add_parser(
        "check",
        help="Run the automatic tests on an attempt and print the result.",
    )
    check.add_argument("root")
    check.add_argument("--level", required=True)
    check.add_argument("--attempt", type=int)

    assemble = commands.add_parser(
        "assemble",
        help="Stitch the accepted levels back into one world image, and optionally build a "
             "playable TMX level from it and register it with the game.",
    )
    assemble.add_argument("root")
    assemble.add_argument("--out", required=True, help="Where to write the stitched world PNG.")
    assemble.add_argument("--no-fallback", action="store_true",
                          help="Leave ground from ungenerated levels black instead of filling "
                               "it with the source map. Off by default so a half-finished run "
                               "is still walkable.")
    assemble.add_argument("--level-dir",
                          help="Also build a playable TMX level here, e.g. "
                               "levels/Frostreach/sunspine_7x6_play.")
    assemble.add_argument("--template-dir", default="levels/Frostreach/ice_wall_gate")
    assemble.add_argument("--tile-size", type=int, default=150,
                          help="TMX tile size, which is what the game divides by: it scales "
                               "the ground by TILESIZE/tile-size, so 150 draws the art at full "
                               "size and anything larger shrinks it. NOT the world's render "
                               "tile size -- passing that (681) renders the map at 0.22.")
    assemble.add_argument("--width-tiles", type=int)
    assemble.add_argument("--height-tiles", type=int)
    assemble.add_argument("--no-register", action="store_true",
                          help="Build the TMX but do not touch the game's level tables.")
    assemble.add_argument("--level-number", type=int, help="Override the level number chosen.")
    assemble.add_argument("--slot", help="Override the menu slot, as ROW,COL.")

    score = commands.add_parser(
        "score",
        help="Report raw footprint IoU per attempt (pre-warp) so draws can be compared.",
    )
    score.add_argument("root")
    score.add_argument("--levels", help="Level selector, for example 01-05 or 01,04,06.")
    return parser


def _build_and_register(args, root, world_png, world_size) -> dict:
    """Turn the stitched PNG into a playable TMX, and put it in the game's level tables.

    Tile geometry defaults to the run's own, so ``bootstrap_level`` writes the background at
    exactly the size it was handed and nothing is resampled.
    """
    from ..bootstrap_from_png import bootstrap_level
    from .register_level import existing_levels, find_existing, register, taken_slots

    # 150 by default, matching the game's TILESIZE, so the ground draws unscaled. This used
    # to default to the world's own tile size, which is a different quantity entirely and made
    # every generated level render at 0.22 until the tmx was edited by hand.
    tile = args.tile_size
    # Round up: a short last row/column is better than cropping the map.
    width_tiles = args.width_tiles or -(-world_size[0] // tile)
    height_tiles = args.height_tiles or -(-world_size[1] // tile)

    level_dir = Path(args.level_dir).resolve()
    bootstrap_level(
        world_png, level_dir,
        width_tiles=width_tiles, height_tiles=height_tiles, tile_size=tile,
        template_dir=Path(args.template_dir).resolve(),
    )
    result = {"level_dir": str(level_dir), "tile_size": tile,
              "tiles": [width_tiles, height_tiles]}
    if args.no_register:
        return result

    repo = Path(__file__).resolve().parents[3]
    # Rebuilding an existing level must land on the number and slot it already has, never
    # allocate new ones -- see find_existing.
    already = find_existing(repo, level_dir.name)
    number = args.level_number or (already[0] if already else max(existing_levels(repo)) + 1)
    if args.slot:
        row, col = (int(part) for part in args.slot.split(","))
    elif already and already[1]:
        row, col = already[1]
    else:
        taken = taken_slots(repo)
        row, col = next((r, c) for r in range(4) for c in range(4) if (r, c) not in taken)
    result.update(register(repo, slug=level_dir.name, number=number,
                           slot=(row, col), world_png=world_png))
    return result


def _run_tile_size(root, world_size) -> int:
    """The tile size the world was rendered at, read from the map it was cut from.

    Not inferred from the dimensions: several sizes divide them exactly -- 22473x12258 is
    divisible by 681 and by 2043 -- and guessing picks the wrong one. The source level's TMX
    states it, so that is what is used.
    """
    import xml.etree.ElementTree as ET

    from .config import load_config

    source = Path(load_config(Path(root) / "config.resolved.json").world_map)
    for name in ("map.tmx", "shell_outline.tmx"):
        candidate = source.parent / name
        if candidate.is_file():
            width = ET.parse(candidate).getroot().get("tilewidth")
            if width and world_size[0] % int(width) == 0:
                return int(width)
    raise ValueError(
        f"no tile size recorded beside {source.name}; pass --tile-size explicitly"
    )


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
            feather=args.feather,
            fit_to_mask=args.fit_to_mask,
            cut_to_mask=args.cut_to_mask,
            padding=args.padding,
        )
        _print(result)
        _review_links("images", [result.get("placement_path"), result.get("accepted_image")])
    elif args.command == "accept":
        result = accept_result(root, args.level, attempt=args.attempt)
        _print(result)
        _review_links("images", [result.get("accepted_image")])
    elif args.command == "unaccept":
        from .result_ingest import unaccept_result

        _print(unaccept_result(root, args.level))
    elif args.command == "compose":
        from .compose import accept_composition, compose_level

        if args.accept is not None:
            result = accept_composition(root, args.level, args.accept)
            _print(result)
            _review_links("composed", [result.get("composed_path")])
        else:
            if not args.prompt:
                raise SystemExit("compose requires --prompt <file> (or --accept <attempt>)")
            result = compose_level(
                root,
                args.level,
                Path(args.prompt),
                player_px=args.player_px,
                player_sprite=Path(args.player_sprite),
                player_count=args.player_count,
            )
            _print(result)
            _review_links("composed attempt", [result.get("input_path"), result.get("composed_path")])
    elif args.command == "run":
        selected = _selected_levels(run, levels=args.levels, region=args.region, state=args.state)
        summary = run_batch(
            root,
            selected,
            args.prompt_file,
            refine=args.refine,
            feather=args.feather,
            retry_reason=args.retry_reason,
            retry_image=args.retry_image,
            retry_note=args.retry_note,
            fit_to_mask=args.fit_to_mask,
            cut_to_mask=args.cut_to_mask,
            padding=args.padding,
        )
        _print(summary)
        images = []
        for item in summary.get("results", []):
            images += [item.get("placement_path"), item.get("accepted_image"), item.get("source_image")]
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
    elif args.command == "assemble":
        from .assemble import assemble_world, core_coverage

        world, info = assemble_world(root, fallback=not args.no_fallback)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        world.save(out)
        info["out"] = str(out)
        info.update(core_coverage(root))
        if args.level_dir:
            info.update(_build_and_register(args, root, out, world.size))
        _print(info)
        _review_links("the assembled world", [str(out)])

    elif args.command == "check":
        from .checks import format_report, run_checks

        report = run_checks(root, args.level, args.attempt)
        print(format_report(report))
        _print(report)
        _review_links("shape error overlay", [report.get("overlay_path")])
    elif args.command == "score":
        from .score_attempts import score_levels

        ids = parse_level_selector(args.levels, run["levels"]) if args.levels else sorted(run["levels"])
        _print(score_levels(root, ids))


if __name__ == "__main__":
    main()
