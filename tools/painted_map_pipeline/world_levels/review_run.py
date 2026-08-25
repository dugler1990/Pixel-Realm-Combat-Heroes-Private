"""Interactive generate -> look -> accept loop over a prepared run.

Wraps the existing orchestrate commands (`run`, `accept`) so the padding chain works:
each level is generated, shown, and only once you accept it do its pixels become the
locked context for the next one. Nothing here reimplements generation.

    python -m tools.painted_map_pipeline.world_levels.review_run <run_root> [--levels 01-06]

Per level, none of which costs a generation except a retry:

    Enter      accept
    t          run the checks and open the shape-error overlay
    f N        re-place with the padding join faded over N px
    w          re-place with the warp onto the mask toggled
    c          re-place with the spill trimmed at the polygon (no warping)
    p          re-place with the neighbours' padding paste off / on
    r ...      retry, optionally with criticism and an image (see parse_retry)
    (--continue opens the menu on the last generation instead of making a new one)\n    r1 ...     retry attaching this attempt's shape-error overlay, with its standing note
    s / q      skip / quit

Every re-place writes a new numbered ``placement_NNN.png``, so nothing is overwritten and a
viewer is never handed a path it has already cached.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from pathlib import Path

from .checks import (
    FOOTPRINT_OVERLAY_DIRECTIVE,
    FOOTPRINT_OVERLAY_NOTE,
    format_report,
    run_checks,
)

CLI = [sys.executable, "-m", "tools.painted_map_pipeline.world_levels.orchestrate"]


class CommandFailed(RuntimeError):
    """An orchestrate subcommand exited non-zero. Carries its last line of stderr."""


def _call(*args: str, fatal: bool = True) -> dict:
    """Run an orchestrate subcommand and return its JSON payload (it prints JSON then links).

    ``fatal=False`` raises CommandFailed instead of exiting, for the re-place commands. A
    re-place can be refused for good reason -- warping a level whose polygon fills the canvas
    has no outline to work from -- and losing the whole session to that means regenerating to
    get back, which costs a call. The refusal is information, not a crash.
    """
    proc = subprocess.run([*CLI, *args], capture_output=True, text=True)
    sys.stdout.write(proc.stdout[-2000:] if proc.returncode else "")
    if proc.returncode:
        if not fatal:
            last = [ln for ln in proc.stderr.strip().splitlines() if ln.strip()]
            raise CommandFailed(last[-1] if last else f"{' '.join(args)} failed")
        sys.stderr.write(proc.stderr[-2000:])
        raise SystemExit(f"{' '.join(args)} failed")
    text = proc.stdout
    start = text.find("{")
    end = text.rfind("}")
    try:
        return json.loads(text[start : end + 1]) if start >= 0 else {}
    except json.JSONDecodeError:
        return {}


def _entry(payload: dict, level_id: str) -> dict:
    for item in payload.get("results", []):
        if item.get("level_id") == level_id:
            return item
    return {}


def newest_attempt(root: Path, level_id: str) -> str | None:
    """The last generation on disk for this level, or None.

    Read from the filesystem rather than run.json's ``latest_candidate``: that field is not
    cleared when a run fails, so it goes on pointing at an older attempt. Attempt directories
    are zero-padded and only ever appear once an image has been placed.
    """
    attempts = sorted((root / "levels" / level_id / "attempts").glob("attempt_*/current.png"))
    return str(attempts[-1]) if attempts else None


def _candidate(root: Path, level_id: str, entry: dict) -> str | None:
    """The image THIS run produced, or None.

    Never falls back to whatever is newest on disk. A failed generation leaves the level's
    ``latest_candidate`` pointing at the previous attempt, and the newest ``current.png`` is
    that attempt too -- so a run that never reached the API had its last image offered for
    review as if it were fresh. That happened for real: level 02 failed three times on a
    missing API key and the loop presented the previous night's placement, complete with a
    black band from a padding strip that had since been rebuilt clean.
    """
    if entry.get("error") or entry.get("state") == "failed":
        return None
    for key in ("placement_path", "accepted_image", "source_image"):
        if entry.get(key):
            return entry[key]
    # Only the attempt this run actually made, never merely the newest one present.
    attempt = entry.get("attempt")
    if attempt is None:
        return None
    produced = root / "levels" / level_id / "attempts" / f"attempt_{int(attempt):03d}" / "current.png"
    return str(produced) if produced.exists() else None


def parse_retry(line: str, root: Path, level_id: str) -> tuple[str, Path | None, str]:
    """Split `r <why> @<image> <note about it>` into its three parts.

    The path is the one token straight after the `@`; everything after that token is the note
    describing it, with or without an `@@` in front. Taking the whole remainder as the filename
    is how a sentence ends up being stat()ed.

    `r1` is the same thing with both halves filled in: the shape-error overlay for this attempt,
    and the standing wording for it. It is by far the commonest retry, and typing the paragraph
    out each time invites it drifting.
    """
    if line[:2].lower() == "r1":
        report = run_checks(root, level_id)
        overlay = report.get("overlay_path")
        if not overlay:
            raise FileNotFoundError(
                report.get("error") or "no shape overlay for this attempt (nothing to point at)"
            )
        extra = line[2:].strip()
        note = f"{FOOTPRINT_OVERLAY_NOTE}. {FOOTPRINT_OVERLAY_DIRECTIVE}"
        if extra:
            note = f"{note} {extra}"
        return "", Path(overlay), note.encode("ascii", "ignore").decode("ascii")

    body = line[1:]
    body, _, tail = body.partition("@@")
    reason, _, token = body.partition("@")
    parts = token.split(None, 1)
    token = parts[0] if parts else ""
    note = " ".join(part.strip() for part in (parts[1] if len(parts) > 1 else "", tail) if part.strip())
    if not token:
        # A note with nothing to attach it to is still criticism; keep it as the reason rather
        # than dropping it silently.
        return " ".join(part for part in (reason.strip(), note) if part), None, ""

    path = Path(token).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"no such image: {path}")
    # A stray non-ASCII character from a paste would make ascii_prompt reject the whole job.
    return reason.strip(), path, note.encode("ascii", "ignore").decode("ascii")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Generate, review and accept levels one by one.")
    parser.add_argument("root")
    parser.add_argument("--levels", help="Selector like 01-06 or 01,04 (default: every unaccepted level)")
    parser.add_argument("--open-with", default="code", help="Command to open the image ('' to just print the path)")
    parser.add_argument("--feather", type=int, default=0, help="Default px to fade the padding join by.")
    parser.add_argument(
        "--continue", dest="resume", action="store_true",
        help="Open the menu on the last generation instead of making a new one. Reviews the "
             "newest attempt that produced an image; everything in the menu then works as it "
             "normally does.",
    )
    parser.add_argument(
        "--prompt-file",
        help="Send this file's contents as the prompt instead of the renderer's built one.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    run = json.loads((root / "run.json").read_text(encoding="utf-8"))
    if args.levels:
        from .batch_runner import parse_level_selector

        selected = parse_level_selector(args.levels, sorted(run["levels"]))
    else:
        selected = [lid for lid in sorted(run["levels"])
                    if run["levels"][lid].get("state") != "accepted"]

    print(f"{len(selected)} level(s) to do: {' '.join(selected)}\n")
    for index, level_id in enumerate(selected, 1):
        pending_retry: tuple[str, ...] = ()
        # --continue applies to the first pass only. Consumed here so that anything reached
        # from the menu afterwards -- a retry above all -- generates as it always would.
        resume = args.resume
        while True:
            # --continue means "pick up where I left off", so it only applies where there is
            # something to pick up. A level that has never generated is generated normally --
            # skipping it would silently do nothing for every level after the last one run.
            existing = newest_attempt(root, level_id) if resume else None
            resume = False
            if existing is not None:
                image = existing
                print(f"--- [{index}/{len(selected)}] level {level_id}: reviewing "
                      f"{Path(existing).parent.name}, not regenerated ---")
            else:
                print(f"--- [{index}/{len(selected)}] level {level_id}: generating ---")
                extra = ("--prompt-file", args.prompt_file) if args.prompt_file else ()
                payload = _call("run", str(root), "--levels", level_id, *extra, *pending_retry)
                pending_retry = ()
                entry = _entry(payload, level_id)
                if entry.get("skipped"):
                    # An explicit --levels selector does not filter by state, so an already
                    # accepted level lands here. Offering Enter would try to accept it twice.
                    print(f"    already {entry['skipped']}, nothing to review\n")
                    break
                image = _candidate(root, level_id, entry)
            if image is None:
                # Generation did not produce anything -- show why instead of offering to
                # accept a level whose job is still 'ready'.
                reason = entry.get("error") or entry.get("state") or "no image was produced"
                print(f"    GENERATION FAILED: {reason}")
                choice = input("    r=retry  s=skip  q=quit > ").strip().lower()
                if choice == "r":
                    continue
                if choice == "q":
                    return 0
                break
            feather = args.feather
            fit = False
            cut = False
            padding = True
            while True:
                print(f"    check: {image}")
                if args.open_with:
                    subprocess.run([args.open_with, "-r", image], check=False)
                raw_choice = input(
                    "    [Enter]=accept  t=run tests  f N=feather  c=cut to the polygon  "
                    "p=padding on/off  "
                    "w=warp onto the mask  "
                    "r [why] [@img] [@@ note]=retry  r1=retry with the shape overlay  s=skip  q=quit > "
                ).strip()
                choice = raw_choice.lower()
                if choice == "t":
                    # Opt-in: the checks never run by themselves, and their wording only
                    # reaches the model if it is typed into an r of your own.
                    report = run_checks(root, level_id)
                    print(textwrap.indent(format_report(report), "    "))
                    if report.get("overlay_path") and args.open_with:
                        subprocess.run([args.open_with, "-r", report["overlay_path"]], check=False)
                    continue
                if choice not in {"w", "c", "p"} and not choice.startswith("f"):
                    break
                # These all re-ingest the SAME generated image, so none costs an API call
                # and each can be applied, undone and retried by eye before accepting.
                if choice == "w":
                    fit = not fit
                    print(f"    warp {'on' if fit else 'off'}")
                elif choice == "p":
                    # The paste puts a neighbour's rendering of shared ground on top of this
                    # level's. Toggling it off re-places the same generation untouched, which
                    # is the only way to see whether a bad-looking join is the paste or the
                    # draw. No API call either way.
                    padding = not padding
                    print(f"    padding paste {'on' if padding else 'OFF'}")
                elif choice == "c":
                    # The non-deforming sibling of the warp: nothing moves, the overshoot is
                    # dropped at the polygon edge. Manual rather than automatic on purpose --
                    # cutting a return that fell short would hide the holes instead of
                    # showing them, so cut_iou is read first and the call is yours.
                    cut = not cut
                    print(f"    cut to the polygon {'on' if cut else 'off'}")
                else:
                    parts = choice.split()
                    feather = (
                        int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else (feather or 24)
                    )
                    # Nothing to fade into on a level with no accepted neighbour, and silently
                    # re-ingesting an identical image reads as the feather being broken.
                    locked = sorted(
                        (root / "levels" / level_id / "jobs").glob(
                            "attempt_*/canvas/locked_overlap_mask.png"
                        )
                    )
                    if locked:
                        import numpy as np
                        from PIL import Image as _Image

                        if not (np.asarray(_Image.open(locked[-1]).convert("L")) > 0).any():
                            print("    no padding on this level (no accepted neighbour yet) - "
                                  "nothing to feather")
                            continue
                raw = sorted((root / "levels" / level_id / "jobs").glob("attempt_*/generated.png"))
                if not raw:
                    print("    no generated image to re-place")
                    continue
                reingest = ["ingest", str(root), "--level", level_id,
                            "--image", str(raw[-1]), "--feather", str(feather)]
                if fit:
                    reingest.append("--fit-to-mask")
                if cut:
                    reingest.append("--cut-to-mask")
                if not padding:
                    reingest += ["--padding", "none"]
                try:
                    payload = _call(*reingest, fatal=False)
                except CommandFailed as refused:
                    # Put the toggle back so the menu still describes what is applied.
                    if choice == "w":
                        fit = not fit
                    elif choice == "c":
                        cut = not cut
                    elif choice == "p":
                        padding = not padding
                    print(f"    REFUSED: {refused}")
                    continue
                image = payload.get("placement_path") or image
                print(f"    re-placed: feather {feather}, warp {'on' if fit else 'off'}, "
                      f"cut {'on' if cut else 'off'}, padding {'on' if padding else 'OFF'}")
            if choice == "r1" or choice.startswith("r1 ") or choice == "r" or choice.startswith("r "):
                # Anything typed after the r is criticism of the picture, which no check can
                # produce, plus optionally the image that shows it.
                try:
                    reason, attached, note = parse_retry(raw_choice, root, level_id)
                except (FileNotFoundError, OSError) as exc:
                    print(f"    {exc}")
                    continue
                pending_retry = ("--retry-reason", reason)
                if attached is not None:
                    pending_retry += ("--retry-image", str(attached), "--retry-note", note)
                    print(f"    attaching {attached.name}")
                continue
            if choice == "q":
                print("stopped; already-accepted levels are kept.")
                return 0
            if choice == "s":
                print("    skipped (not accepted, so it will not pad its neighbours)")
                break
            _call("accept", str(root), "--level", level_id)
            print(f"    accepted {level_id}\n")
            break
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
