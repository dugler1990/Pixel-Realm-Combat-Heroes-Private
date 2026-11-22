"""Open the level studio in the browser.

    python -m tools.painted_map_pipeline.world_levels.studio_page [--port 8766]

Run from the repo root. The cell-review command is still
``python -m tools.painted_map_pipeline.world_levels.review_page <run_root>``.
"""

from __future__ import annotations

import argparse

from .studio import Studio, serve


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pick, compose, scale and grid a level, then review it.")
    parser.add_argument("--port", type=int, default=8766, help="8765 is the SAM page, 8767 the outfit page.")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    serve(Studio(), args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
