"""Open the level review page: review_run's generate -> look -> accept loop in the browser.

    python -m tools.painted_map_pipeline.world_levels.review_page <run_root> [--levels 01-06]

Run from the repo root. Same actions as the console loop, plus the align view: drag the
padding onto the generation, then Align colours re-places with that offset. Use the page or
review_run on a run, not both at once.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .batch_runner import parse_level_selector
from .review_web import ReviewPage, serve


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Review, re-place and accept levels in the browser.")
    parser.add_argument("root")
    parser.add_argument("--levels", help="Selector like 01-06 or 01,04 (default: every level)")
    parser.add_argument("--feather", type=int, default=0, help="Default px to fade the padding join by.")
    parser.add_argument("--prompt-file", help="Send this file's contents as the prompt instead of the renderer's built one.")
    parser.add_argument("--port", type=int, default=8766, help="8765 is the SAM page's.")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    run = json.loads((root / "run.json").read_text(encoding="utf-8"))
    every = sorted(run["levels"])
    levels = parse_level_selector(args.levels, every) if args.levels else every
    prompt_file = str(Path(args.prompt_file).resolve()) if args.prompt_file else None
    page = ReviewPage(root, levels, feather=args.feather, prompt_file=prompt_file)
    serve(page, args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
