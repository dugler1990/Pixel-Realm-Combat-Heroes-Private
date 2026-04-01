import argparse
import csv
import os
import re
import subprocess
import sys
from datetime import datetime


COUNTS = [100, 150, 200, 250, 300]
BACKENDS = ["quadtree", "grid"]
GRID_CELL_SIZES = [150, 300, 450]
TOGGLE_MODES = [
    ("off", False, False),
    ("on", True, True),
]


def _read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _as_float(row, key):
    try:
        return float(row.get(key, 0))
    except ValueError:
        return 0.0


def _as_int(row, key):
    try:
        return int(float(row.get(key, 0)))
    except ValueError:
        return 0


def _entity_count_from_run_label(row):
    """Prefer run_label; CSV rows may not match header if schema evolved."""
    label = row.get("run_label", "") or ""
    m = re.search(r"_(\d+)_(quadtree|grid)_", label)
    if m:
        return int(m.group(1))
    return _as_int(row, "entity_count")


def _backend_from_run_label(row):
    label = row.get("run_label", "") or ""
    m = re.search(r"_(\d+)_(quadtree|grid)_", label)
    if m:
        return m.group(2)
    return row.get("backend", "") or ""


def _collision_mode_from_row(row):
    mode = row.get("collision_mode", "") or ""
    if mode:
        return mode
    label = row.get("run_label", "") or ""
    m = re.search(r"_cell\d+_([a-zA-Z0-9_]+)_(?:off|on|floor_only|cap[\d.]+|floor_cap[\d.]+)$", label)
    if m:
        return m.group(1)
    return "legacy"


def _variant_from_run_label(row):
    if row.get("collision_mode"):
        label = row.get("run_label", "") or ""
        m = re.search(r"_cell\d+_[a-zA-Z0-9_]+_(.+)$", label)
        if m:
            return m.group(1)
    label = row.get("run_label", "") or ""
    m = re.search(r"_cell\d+_(.+)$", label)
    if m:
        return m.group(1)
    floor_enabled = row.get("pushback_floor_enabled") == "True"
    cap_enabled = row.get("pushback_cap_enabled") == "True"
    max_cap = row.get("pushback_max_cap", "")
    if floor_enabled and cap_enabled and max_cap:
        return f"floor_cap{max_cap}"
    if floor_enabled and not cap_enabled:
        return "floor_only"
    if cap_enabled and max_cap:
        return f"cap{max_cap}"
    return "off"


def run_matrix(
    auto_seconds=20,
    warmup_seconds=1.5,
    grid_cell_sizes=None,
    cap_sweep=False,
    cap_values=None,
    enemy_type=None,
    backends=None,
    collision_modes=None,
):
    if grid_cell_sizes is None:
        grid_cell_sizes = GRID_CELL_SIZES
    if cap_values is None:
        cap_values = [8.0, 12.0, 16.0]
    if backends is None:
        backends = list(BACKENDS)
    if collision_modes is None:
        collision_modes = ["legacy"]
    code_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.normpath(os.path.join(code_dir, ".."))
    csv_path = os.path.normpath(os.path.join(code_dir, "..", "logs", "benchmark_metrics.csv"))
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_prefix = f"matrix_{stamp}"

    # With cap sweep enabled in benchmark_runtime:
    # off, floor_only, cap{v}, floor_cap{v} for each v.
    variants = (2 + (2 * len(cap_values))) if cap_sweep else len(TOGGLE_MODES)
    variants *= max(1, len(collision_modes))
    quadtree_cases = (
        len(COUNTS) * variants if "quadtree" in backends else 0
    )
    grid_cases = (
        len(COUNTS) * variants * len(grid_cell_sizes) if "grid" in backends else 0
    )
    total_runs = quadtree_cases + grid_cases
    env = os.environ.copy()
    env.update(
        {
            "PRCH_BENCHMARK_ENABLED": "1",
            "PRCH_BENCHMARK_MATRIX_ENABLED": "1",
            "PRCH_BENCHMARK_MATRIX_COUNTS": ",".join(str(x) for x in COUNTS),
            "PRCH_BENCHMARK_MATRIX_BACKENDS": ",".join(backends),
            "PRCH_BENCHMARK_GRID_CELL_SIZES": ",".join(str(x) for x in grid_cell_sizes),
            "PRCH_BENCHMARK_MATRIX_PREFIX": run_prefix,
            "PRCH_BENCHMARK_AUTO_RUN_SECONDS": str(auto_seconds),
            "PRCH_BENCHMARK_WARMUP_SECONDS": str(warmup_seconds),
            "PRCH_BENCHMARK_METRICS_ENABLED": "1",
            "PRCH_BENCHMARK_METRICS_CSV_PATH": "../logs/benchmark_metrics.csv",
            "PRCH_BENCHMARK_SEED": "1337",
            "PRCH_BENCHMARK_MATRIX_CAP_SWEEP": "1" if cap_sweep else "0",
            "PRCH_BENCHMARK_MATRIX_CAP_VALUES": ",".join(str(x) for x in cap_values),
            "PRCH_BENCHMARK_MATRIX_COLLISION_MODES": ",".join(collision_modes),
        }
    )
    if enemy_type:
        env["PRCH_BENCHMARK_ENEMY_TYPE"] = enemy_type

    print(
        f"[BENCH] Starting one-window matrix: cases={total_runs}, "
        f"seconds_per_case={auto_seconds}, warmup_seconds={warmup_seconds}, "
        f"backends={backends}, collision_modes={collision_modes}, grid_cell_sizes={grid_cell_sizes}, cap_sweep={cap_sweep}, "
        f"enemy_type={enemy_type or '(default)'}, prefix={run_prefix}"
    )
    proc = subprocess.run(
        [sys.executable, "Main2.py"],
        cwd=code_dir,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        print(f"[BENCH] Matrix run failed (exit={proc.returncode})")
        return 1

    rows = [r for r in _read_rows(csv_path) if r.get("run_label", "").startswith(run_prefix)]
    rows.sort(
        key=lambda r: (
            _entity_count_from_run_label(r),
            _backend_from_run_label(r),
            int(float(r.get("grid_cell_size", 0) or 0)),
            _collision_mode_from_row(r),
            _variant_from_run_label(r),
        )
    )
    if not rows:
        print("No benchmark rows found.")
        return 1
    if len(rows) != total_runs:
        print(f"[BENCH] Warning: expected {total_runs} rows, got {len(rows)}")

    header = (
        "entity_count | backend | grid_cell_size | collision_mode | variant | avg_fps | p95_ms | "
        "queries | candidates | resolved | maint_u"
    )
    print("\nComparison table")
    print(header)
    print("-|-|-|-|-|-|-|-|-|-|-")
    for row in rows:
        grid_cell_size = row.get("grid_cell_size", "") or "-"
        collision_mode = _collision_mode_from_row(row)
        variant = _variant_from_run_label(row)
        print(
            f"{_entity_count_from_run_label(row)} | {_backend_from_run_label(row)} | {grid_cell_size} | {collision_mode} | {variant} | "
            f"{_as_float(row, 'avg_fps'):.2f} | {_as_float(row, 'p95_frame_ms'):.2f} | "
            f"{_as_int(row, 'broadphase_queries')} | {_as_int(row, 'candidate_collisions')} | "
            f"{_as_int(row, 'resolved_collisions')} | {_as_int(row, 'maintenance_upsert')}"
        )

    summary_path = os.path.join(repo_root, "logs", f"benchmark_comparison_{stamp}.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("# Benchmark Comparison\n\n")
        f.write(header + "\n")
        f.write("-|-|-|-|-|-|-|-|-|-|-\n")
        for row in rows:
            grid_cell_size = row.get("grid_cell_size", "") or "-"
            collision_mode = _collision_mode_from_row(row)
            variant = _variant_from_run_label(row)
            f.write(
                f"{_entity_count_from_run_label(row)} | {_backend_from_run_label(row)} | {grid_cell_size} | {collision_mode} | {variant} | "
                f"{_as_float(row, 'avg_fps'):.2f} | {_as_float(row, 'p95_frame_ms'):.2f} | "
                f"{_as_int(row, 'broadphase_queries')} | {_as_int(row, 'candidate_collisions')} | "
                f"{_as_int(row, 'resolved_collisions')} | {_as_int(row, 'maintenance_upsert')}\n"
            )
    print(f"\nWrote summary: {summary_path}")
    return 0


def summarize_from_csv(run_prefix, csv_path=None):
    """Re-print comparison table for an existing run (no Main2)."""
    code_dir = os.path.dirname(os.path.abspath(__file__))
    if csv_path is None:
        csv_path = os.path.normpath(os.path.join(code_dir, "..", "logs", "benchmark_metrics.csv"))
    rows = [r for r in _read_rows(csv_path) if r.get("run_label", "").startswith(run_prefix)]
    rows.sort(
        key=lambda r: (
            _entity_count_from_run_label(r),
            _backend_from_run_label(r),
            int(float(r.get("grid_cell_size", 0) or 0)),
            _collision_mode_from_row(r),
            _variant_from_run_label(r),
        )
    )
    if not rows:
        print(f"No rows for prefix {run_prefix!r}")
        return 1
    header = (
        "entity_count | backend | grid_cell_size | collision_mode | variant | avg_fps | p95_ms | "
        "queries | candidates | resolved | maint_u"
    )
    print("\nComparison table")
    print(header)
    print("-|-|-|-|-|-|-|-|-|-|-")
    for row in rows:
        grid_cell_size = row.get("grid_cell_size", "") or "-"
        collision_mode = _collision_mode_from_row(row)
        variant = _variant_from_run_label(row)
        print(
            f"{_entity_count_from_run_label(row)} | {_backend_from_run_label(row)} | {grid_cell_size} | {collision_mode} | {variant} | "
            f"{_as_float(row, 'avg_fps'):.2f} | {_as_float(row, 'p95_frame_ms'):.2f} | "
            f"{_as_int(row, 'broadphase_queries')} | {_as_int(row, 'candidate_collisions')} | "
            f"{_as_int(row, 'resolved_collisions')} | {_as_int(row, 'maintenance_upsert')}"
        )
    return 0


def _parse_grid_cells(s):
    out = []
    for token in s.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError:
            pass
    return out or None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Run benchmark matrix (Main2) with env-driven PRCH_BENCHMARK_* settings."
    )
    ap.add_argument(
        "--summary-prefix",
        metavar="PREFIX",
        default=None,
        help="Only print comparison table from logs/benchmark_metrics.csv for this run_label prefix (no game)",
    )
    ap.add_argument("seconds", nargs="?", type=int, default=3, help="Measurement seconds per case")
    ap.add_argument("warmup", nargs="?", type=float, default=1.5, help="Warmup seconds per case")
    ap.add_argument(
        "--grid-cells",
        default=",".join(str(x) for x in GRID_CELL_SIZES),
        help="Comma-separated grid cell sizes (grid backend only), e.g. 450",
    )
    ap.add_argument(
        "--cap-sweep",
        action="store_true",
        help="Sweep pushback cap: off + cap at each value from --cap-values (floor on when cap on)",
    )
    ap.add_argument(
        "--cap-values",
        default="8,12,16",
        help="With --cap-sweep, max displacement cap values to test",
    )
    ap.add_argument("--enemy", default=None, help="Enemy type for benchmark spawns, e.g. ice_ghost")
    ap.add_argument(
        "--collision-modes",
        default="legacy",
        help="Comma-separated collision modes to benchmark, e.g. legacy,simple_swarm",
    )
    ap.add_argument(
        "--backends",
        default="quadtree,grid",
        help="Comma-separated broadphase backends to benchmark: quadtree, grid (grid-only: --backends grid)",
    )
    args = ap.parse_args()
    if args.summary_prefix:
        raise SystemExit(summarize_from_csv(args.summary_prefix.strip()))
    grid_cell_sizes = _parse_grid_cells(args.grid_cells)
    cap_vals = []
    for t in args.cap_values.split(","):
        t = t.strip()
        if not t:
            continue
        try:
            cap_vals.append(float(t))
        except ValueError:
            pass
    if not cap_vals:
        cap_vals = [8.0, 12.0, 16.0]
    backends = [b.strip() for b in args.backends.split(",") if b.strip()]
    if not backends:
        backends = list(BACKENDS)
    collision_modes = [m.strip() for m in args.collision_modes.split(",") if m.strip()]
    if not collision_modes:
        collision_modes = ["legacy"]
    raise SystemExit(
        run_matrix(
            auto_seconds=args.seconds,
            warmup_seconds=args.warmup,
            grid_cell_sizes=grid_cell_sizes,
            cap_sweep=args.cap_sweep,
            cap_values=cap_vals,
            enemy_type=args.enemy,
            backends=backends,
            collision_modes=collision_modes,
        )
    )
