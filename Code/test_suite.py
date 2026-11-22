#!/usr/bin/env python3
"""Run the test suite scenes in the benchmark arena (black floor, magenta walls).

From the Code directory:

    python test_suite.py                         # a window; each scene held for you to watch
    python test_suite.py --scenario arrows_stop  # one scene (repeatable)
    python test_suite.py --headless              # no window, pass/fail only
    python test_suite.py --list                  # the scenes

Results: ../logs/test_suite_latest.json. Scenes: test_suite_driver.SCENARIOS.
"""

import argparse
import json
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="In-game test suite via a Main2 subprocess.")
    parser.add_argument("--scenario", action="append", dest="scenarios", help="Run only this scene; repeatable")
    parser.add_argument("--headless", action="store_true", help="No window, fast, pass/fail only")
    parser.add_argument("--hold-seconds", type=float, default=None,
                        help="Seconds each scene stays on screen after it is decided (default: 4 visible, 0 headless)")
    parser.add_argument("--mesh-pack", default="barb", help="The hero's mesh pack (default barb)")
    parser.add_argument("--layout-dir", default="../levels/benchmark", help="Layout (default: the benchmark arena)")
    parser.add_argument("--output", default="../logs/test_suite_latest.json", help="Results JSON path")
    parser.add_argument("--json", action="store_true", help="Print the results JSON")
    parser.add_argument("--list", action="store_true", help="List the scenes and exit")
    args = parser.parse_args()

    code_dir = os.path.dirname(os.path.abspath(__file__))
    if args.list:
        sys.path.insert(0, code_dir)
        from test_suite_driver import EXTRA_SCENARIOS, SCENARIOS
        for scene in SCENARIOS + EXTRA_SCENARIOS:
            print(f"{scene.NAME}: {scene.WATCH}")
        return 0

    output_path = args.output if os.path.isabs(args.output) else os.path.normpath(os.path.join(code_dir, args.output))
    hold = args.hold_seconds if args.hold_seconds is not None else (0.0 if args.headless else 4.0)
    env = os.environ.copy()
    env.update({
        "PRCH_TEST_SUITE_ENABLED": "1",
        "PRCH_TEST_SUITE_LAYOUT_DIR": args.layout_dir,
        "PRCH_TEST_SUITE_OUTPUT": output_path,
        "PRCH_TEST_SUITE_HOLD_SECONDS": str(hold),
        "PRCH_TEST_SUITE_MESH_PACK": args.mesh_pack,
        "PRCH_TEST_SUITE_SCENARIOS": ",".join(args.scenarios) if args.scenarios else "all",
        "PRCH_BENCHMARK_GRASS_ENABLED": "0",     # a bare arena floor: no grass over the scenes
    })
    if args.headless:
        env.update({"PRCH_TEST_SUITE_FAST": "1", "PRCH_TEST_SUITE_VISIBLE": "0",
                    "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy", "RENDER_BACKEND": "cpu",
                    # no window draws the mesh: hit it anyway, as the game would with one
                    "PRCH_MESH_HIT_WHEN_UNDRAWN": "1"})
    else:
        env.update({"PRCH_TEST_SUITE_FAST": "0", "PRCH_TEST_SUITE_VISIBLE": "1"})
        env.pop("SDL_VIDEODRIVER", None)
        env.pop("SDL_AUDIODRIVER", None)
    if os.path.isfile(output_path):
        os.remove(output_path)

    proc = subprocess.run([sys.executable, "Main2.py"], cwd=code_dir, env=env, check=False)

    result = {"ok": False, "scenarios": [], "error": "output missing"}
    if os.path.isfile(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            result = json.load(f)
    else:
        result["error"] = f"Main2 exited with code {proc.returncode} and wrote no results"

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Test suite ({'headless' if args.headless else 'visible'})")
        for row in result.get("scenarios", []):
            print(f"- {row.get('name')}: {str(row.get('status', '')).upper()} ({row.get('details', '')})")
        print(f"Overall: {'PASS' if result.get('ok') else 'FAIL'}")
        if result.get("error") and not result.get("scenarios"):
            print(f"Error: {result['error']}")
    if proc.returncode == 0 and not result.get("ok", False):
        return 1
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
