#!/usr/bin/env python3
"""Launch Main2 in RTS validation mode and report scenario results."""

import argparse
import json
import os
import subprocess
import sys


def _default_output_path():
    code_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(code_dir, "..", "logs", "rts_validation_latest.json"))


def main():
    parser = argparse.ArgumentParser(
        description="Run in-game RTS validation via Main2 subprocess."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON from output file",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        help="Run only named scenario(s); repeatable",
    )
    parser.add_argument(
        "--layout-dir",
        default="../levels/tmx",
        help="TMX layout directory (default: ../levels/tmx)",
    )
    parser.add_argument(
        "--output",
        default="../logs/rts_validation_latest.json",
        help="Results JSON path (written by Main2)",
    )
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="Per-scenario timeout fallback (visible uses per-scenario limits in driver)",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="CI mode: dummy SDL, fast teleports, ~15s (no window)",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=None,
        help="Seconds to hold each passed scenario on screen (default: 8 visible, 0 headless)",
    )
    args = parser.parse_args()

    headless = args.headless
    max_seconds = args.max_seconds if args.max_seconds is not None else (30.0 if headless else 38.0)
    hold_seconds = args.hold_seconds if args.hold_seconds is not None else (0.0 if headless else 8.0)

    code_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = args.output
    if not os.path.isabs(output_path):
        output_path = os.path.normpath(os.path.join(code_dir, output_path))

    env = os.environ.copy()
    env["PRCH_RTS_VALIDATION_ENABLED"] = "1"
    env["PRCH_RTS_VALIDATION_LAYOUT_DIR"] = args.layout_dir
    env["PRCH_RTS_VALIDATION_OUTPUT"] = output_path
    env["PRCH_RTS_VALIDATION_MAX_SECONDS"] = str(max_seconds)
    env["PRCH_RTS_VALIDATION_HOLD_SECONDS"] = str(hold_seconds)
    if headless:
        env["PRCH_RTS_VALIDATION_FAST"] = "1"
        env["PRCH_RTS_VALIDATION_VISIBLE"] = "0"
        env["SDL_VIDEODRIVER"] = "dummy"
        env["SDL_AUDIODRIVER"] = "dummy"
    else:
        env["PRCH_RTS_VALIDATION_FAST"] = "0"
        env["PRCH_RTS_VALIDATION_VISIBLE"] = "1"
        env.pop("SDL_VIDEODRIVER", None)
        env.pop("SDL_AUDIODRIVER", None)
    if args.scenarios:
        env["PRCH_RTS_VALIDATION_SCENARIOS"] = ",".join(args.scenarios)
    else:
        env["PRCH_RTS_VALIDATION_SCENARIOS"] = "all"

    if os.path.isfile(output_path):
        os.remove(output_path)

    proc = subprocess.run(
        [sys.executable, "Main2.py"],
        cwd=code_dir,
        env=env,
        check=False,
    )

    result = {"ok": False, "scenarios": [], "error": "output missing"}
    if os.path.isfile(output_path):
        with open(output_path, "r", encoding="utf-8") as f:
            result = json.load(f)
    elif proc.returncode == 0:
        result["error"] = "validation finished but output file not found"
    elif proc.returncode != 0:
        result["error"] = f"Main2 exited with code {proc.returncode} (no fresh results file)"

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        mode = "headless" if headless else "visible"
        print(f"RTS validation results ({mode})")
        for row in result.get("scenarios", []):
            status = "PASS" if row.get("passed") else "FAIL"
            print(f"- {row.get('name')}: {status} ({row.get('details', '')})")
        print(f"Overall: {'PASS' if result.get('ok') else 'FAIL'}")
        if result.get("error") and not result.get("scenarios"):
            print(f"Error: {result['error']}")

    exit_code = proc.returncode
    if proc.returncode == 0 and not result.get("ok", False):
        exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
