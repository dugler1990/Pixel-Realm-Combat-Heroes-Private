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


def _grass_wind_mode_from_row(row):
    mode = row.get("grass_wind_mode", "") or ""
    return mode or "off"


def _grass_disturbance_from_row(row):
    value = row.get("grass_disturbance_enabled", "")
    if value in {"True", "False"}:
        return "on" if value == "True" else "off"
    return "off"


def _simple_swarm_neighbors_from_row(row):
    value = row.get("simple_swarm_neighbor_limit", "")
    if value:
        return _as_int(row, "simple_swarm_neighbor_limit")
    label = row.get("run_label", "") or ""
    m = re.search(r"_n(\d+)(?:_|$)", label)
    if m:
        return int(m.group(1))
    return 0


def _variant_from_run_label(row):
    if row.get("pushback_variant"):
        return row.get("pushback_variant")
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
    counts=None,
    grid_cell_sizes=None,
    cap_sweep=False,
    cap_values=None,
    enemy_type=None,
    enemy_mix=None,
    backends=None,
    collision_modes=None,
    simple_swarm_neighbor_limits=None,
    grass_enabled=False,
    grass_wind_modes=None,
    grass_disturbance_modes=None,
    layout_dir=None,
):
    if counts is None:
        counts = COUNTS
    if grid_cell_sizes is None:
        grid_cell_sizes = GRID_CELL_SIZES
    if cap_values is None:
        cap_values = [8.0, 12.0, 16.0]
    if backends is None:
        backends = list(BACKENDS)
    if collision_modes is None:
        collision_modes = ["legacy"]
    if simple_swarm_neighbor_limits is None:
        simple_swarm_neighbor_limits = [4]
    if grass_wind_modes is None:
        grass_wind_modes = ["legacy_tile"]
    if grass_disturbance_modes is None:
        grass_disturbance_modes = [True]
    if grass_enabled and not layout_dir:
        layout_dir = "../levels/tmx"
    code_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.normpath(os.path.join(code_dir, ".."))
    csv_path = os.path.normpath(os.path.join(code_dir, "..", "logs", "benchmark_metrics.csv"))
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_prefix = f"matrix_{stamp}"

    # With cap sweep enabled in benchmark_runtime:
    # off, floor_only, cap{v}, floor_cap{v} for each v.
    base_variants = (2 + (2 * len(cap_values))) if cap_sweep else len(TOGGLE_MODES)
    variants = 0
    for mode in collision_modes:
        multiplier = (
            max(1, len(simple_swarm_neighbor_limits))
            if mode == "simple_swarm"
            else 1
        )
        variants += base_variants * multiplier
    if grass_enabled:
        variants *= max(1, len(grass_wind_modes))
        variants *= max(1, len(grass_disturbance_modes))
    quadtree_cases = (
        len(counts) * variants if "quadtree" in backends else 0
    )
    grid_cases = (
        len(counts) * variants * len(grid_cell_sizes) if "grid" in backends else 0
    )
    total_runs = quadtree_cases + grid_cases
    env = os.environ.copy()
    env.update(
        {
            "PRCH_BENCHMARK_ENABLED": "1",
            "PRCH_BENCHMARK_MATRIX_ENABLED": "1",
            "PRCH_BENCHMARK_MATRIX_COUNTS": ",".join(str(x) for x in counts),
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
            "PRCH_BENCHMARK_MATRIX_SIMPLE_SWARM_NEIGHBORS": ",".join(
                str(x) for x in simple_swarm_neighbor_limits
            ),
            "PRCH_BENCHMARK_GRASS_ENABLED": "1" if grass_enabled else "0",
            "PRCH_BENCHMARK_MATRIX_GRASS_WIND_MODES": ",".join(grass_wind_modes),
            "PRCH_BENCHMARK_MATRIX_GRASS_DISTURBANCE_MODES": ",".join(
                "1" if mode else "0" for mode in grass_disturbance_modes
            ),
        }
    )
    if enemy_type:
        env["PRCH_BENCHMARK_ENEMY_TYPE"] = enemy_type
    if enemy_mix:
        env["PRCH_BENCHMARK_ENEMY_MIX"] = enemy_mix.strip()
    if layout_dir:
        env["PRCH_BENCHMARK_LAYOUT_DIR"] = layout_dir

    print(
        f"[BENCH] Starting one-window matrix: cases={total_runs}, "
        f"seconds_per_case={auto_seconds}, warmup_seconds={warmup_seconds}, "
        f"backends={backends}, collision_modes={collision_modes}, grid_cell_sizes={grid_cell_sizes}, cap_sweep={cap_sweep}, "
        f"simple_swarm_neighbor_limits={simple_swarm_neighbor_limits}, "
        f"enemy_type={enemy_type or '(default)'}, enemy_mix={enemy_mix or '(none)'}, grass_enabled={grass_enabled}, "
        f"grass_wind_modes={grass_wind_modes}, grass_disturbance_modes={grass_disturbance_modes}, "
        f"layout_dir={layout_dir or '(default)'}, prefix={run_prefix}"
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
            _simple_swarm_neighbors_from_row(r),
            _grass_wind_mode_from_row(r),
            _grass_disturbance_from_row(r),
            _variant_from_run_label(r),
        )
    )
    if not rows:
        print("No benchmark rows found.")
        return 1
    if len(rows) != total_runs:
        print(f"[BENCH] Warning: expected {total_runs} rows, got {len(rows)}")

    header = (
        "entity_count | backend | grid_cell_size | collision_mode | swarm_n | grass_wind | disturbance | variant | avg_fps | p95_ms | "
        "grass_ms | grass_visible | grass_custom | grass_force | queries | candidates | resolved | maint_u | i_emit | i_resolve | i_rej_team | i_rej_target | i_damage | i_effect_state | i_rej_missing | i_rej_policy | i_rej_gate | i_rej_norecv | aggro_checks | aggro_allowed"
    )
    print("\nComparison table")
    print(header)
    print("-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-")
    for row in rows:
        grid_cell_size = row.get("grid_cell_size", "") or "-"
        collision_mode = _collision_mode_from_row(row)
        swarm_neighbors = _simple_swarm_neighbors_from_row(row)
        grass_wind = _grass_wind_mode_from_row(row)
        grass_disturbance = _grass_disturbance_from_row(row)
        variant = _variant_from_run_label(row)
        print(
            f"{_entity_count_from_run_label(row)} | {_backend_from_run_label(row)} | {grid_cell_size} | {collision_mode} | {swarm_neighbors} | {grass_wind} | {grass_disturbance} | {variant} | "
            f"{_as_float(row, 'avg_fps'):.2f} | {_as_float(row, 'p95_frame_ms'):.2f} | "
            f"{_as_float(row, 'grass_update_render_ms_avg'):.2f} | {_as_float(row, 'grass_visible_tiles'):.2f} | "
            f"{_as_float(row, 'grass_custom_tiles'):.2f} | {_as_int(row, 'grass_force_calls')} | "
            f"{_as_int(row, 'broadphase_queries')} | {_as_int(row, 'candidate_collisions')} | "
            f"{_as_int(row, 'resolved_collisions')} | {_as_int(row, 'maintenance_upsert')} | "
            f"{_as_int(row, 'interactions_emitted_total')} | {_as_int(row, 'interactions_resolved_total')} | "
            f"{_as_int(row, 'interactions_rejected_team')} | {_as_int(row, 'interactions_rejected_target')} | "
            f"{_as_int(row, 'interactions_damage_applied_total')} | "
            f"{_as_int(row, 'interactions_effect_state_total')} | "
            f"{_as_int(row, 'interactions_rejected_missing_target')} | "
            f"{_as_int(row, 'interactions_rejected_team_policy')} | "
            f"{_as_int(row, 'interactions_rejected_target_gate')} | "
            f"{_as_int(row, 'interactions_rejected_no_receive')} | "
            f"{_as_int(row, 'aggro_checks_total')} | {_as_int(row, 'aggro_allowed_total')}"
        )

    summary_path = os.path.join(repo_root, "logs", f"benchmark_comparison_{stamp}.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("# Benchmark Comparison\n\n")
        f.write(header + "\n")
        f.write("-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-\n")
        for row in rows:
            grid_cell_size = row.get("grid_cell_size", "") or "-"
            collision_mode = _collision_mode_from_row(row)
            swarm_neighbors = _simple_swarm_neighbors_from_row(row)
            grass_wind = _grass_wind_mode_from_row(row)
            grass_disturbance = _grass_disturbance_from_row(row)
            variant = _variant_from_run_label(row)
            f.write(
                f"{_entity_count_from_run_label(row)} | {_backend_from_run_label(row)} | {grid_cell_size} | {collision_mode} | {swarm_neighbors} | {grass_wind} | {grass_disturbance} | {variant} | "
                f"{_as_float(row, 'avg_fps'):.2f} | {_as_float(row, 'p95_frame_ms'):.2f} | "
                f"{_as_float(row, 'grass_update_render_ms_avg'):.2f} | {_as_float(row, 'grass_visible_tiles'):.2f} | "
                f"{_as_float(row, 'grass_custom_tiles'):.2f} | {_as_int(row, 'grass_force_calls')} | "
                f"{_as_int(row, 'broadphase_queries')} | {_as_int(row, 'candidate_collisions')} | "
                f"{_as_int(row, 'resolved_collisions')} | {_as_int(row, 'maintenance_upsert')} | "
                f"{_as_int(row, 'interactions_emitted_total')} | {_as_int(row, 'interactions_resolved_total')} | "
                f"{_as_int(row, 'interactions_rejected_team')} | {_as_int(row, 'interactions_rejected_target')} | "
                f"{_as_int(row, 'interactions_damage_applied_total')} | "
                f"{_as_int(row, 'interactions_effect_state_total')} | "
                f"{_as_int(row, 'interactions_rejected_missing_target')} | "
                f"{_as_int(row, 'interactions_rejected_team_policy')} | "
                f"{_as_int(row, 'interactions_rejected_target_gate')} | "
                f"{_as_int(row, 'interactions_rejected_no_receive')} | "
                f"{_as_int(row, 'aggro_checks_total')} | {_as_int(row, 'aggro_allowed_total')}\n"
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
            _simple_swarm_neighbors_from_row(r),
            _grass_wind_mode_from_row(r),
            _grass_disturbance_from_row(r),
            _variant_from_run_label(r),
        )
    )
    if not rows:
        print(f"No rows for prefix {run_prefix!r}")
        return 1
    header = (
        "entity_count | backend | grid_cell_size | collision_mode | swarm_n | grass_wind | disturbance | variant | avg_fps | p95_ms | "
        "grass_ms | grass_visible | grass_custom | grass_force | queries | candidates | resolved | maint_u | i_emit | i_resolve | i_rej_team | i_rej_target | i_damage | i_effect_state | i_rej_missing | i_rej_policy | i_rej_gate | i_rej_norecv | aggro_checks | aggro_allowed"
    )
    print("\nComparison table")
    print(header)
    print("-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-|-")
    for row in rows:
        grid_cell_size = row.get("grid_cell_size", "") or "-"
        collision_mode = _collision_mode_from_row(row)
        swarm_neighbors = _simple_swarm_neighbors_from_row(row)
        grass_wind = _grass_wind_mode_from_row(row)
        grass_disturbance = _grass_disturbance_from_row(row)
        variant = _variant_from_run_label(row)
        print(
            f"{_entity_count_from_run_label(row)} | {_backend_from_run_label(row)} | {grid_cell_size} | {collision_mode} | {swarm_neighbors} | {grass_wind} | {grass_disturbance} | {variant} | "
            f"{_as_float(row, 'avg_fps'):.2f} | {_as_float(row, 'p95_frame_ms'):.2f} | "
            f"{_as_float(row, 'grass_update_render_ms_avg'):.2f} | {_as_float(row, 'grass_visible_tiles'):.2f} | "
            f"{_as_float(row, 'grass_custom_tiles'):.2f} | {_as_int(row, 'grass_force_calls')} | "
            f"{_as_int(row, 'broadphase_queries')} | {_as_int(row, 'candidate_collisions')} | "
            f"{_as_int(row, 'resolved_collisions')} | {_as_int(row, 'maintenance_upsert')} | "
            f"{_as_int(row, 'interactions_emitted_total')} | {_as_int(row, 'interactions_resolved_total')} | "
            f"{_as_int(row, 'interactions_rejected_team')} | {_as_int(row, 'interactions_rejected_target')} | "
            f"{_as_int(row, 'interactions_damage_applied_total')} | "
            f"{_as_int(row, 'interactions_effect_state_total')} | "
            f"{_as_int(row, 'interactions_rejected_missing_target')} | "
            f"{_as_int(row, 'interactions_rejected_team_policy')} | "
            f"{_as_int(row, 'interactions_rejected_target_gate')} | "
            f"{_as_int(row, 'interactions_rejected_no_receive')} | "
            f"{_as_int(row, 'aggro_checks_total')} | {_as_int(row, 'aggro_allowed_total')}"
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


def _parse_int_list(s):
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
        "--enemy-mix",
        default=None,
        dest="enemy_mix",
        help="Per-type counts, e.g. raccoon:30,ice_mage:10 (pair with --counts 40)",
    )
    ap.add_argument(
        "--grass",
        action="store_true",
        help="Enable grass benchmark instrumentation and scenario sweep support",
    )
    ap.add_argument(
        "--grass-wind-modes",
        default="legacy_tile,shared_patch",
        help="Comma-separated grass wind modes when --grass: legacy_tile (per-tile phase), shared_patch (one angle for whole patch)",
    )
    ap.add_argument(
        "--grass-disturbance",
        default="on,off",
        help="Comma-separated grass disturbance modes when --grass is enabled: on,off",
    )
    ap.add_argument(
        "--layout-dir",
        default=None,
        help="Benchmark layout directory override, e.g. ../levels/tmx for grass-heavy runs",
    )
    ap.add_argument(
        "--collision-modes",
        default="legacy",
        help="Comma-separated collision modes to benchmark, e.g. legacy,simple_swarm",
    )
    ap.add_argument(
        "--swarm-neighbors",
        default="4",
        help="Comma-separated simple_swarm neighbor limits to benchmark, e.g. 2,4,6",
    )
    ap.add_argument(
        "--backends",
        default="quadtree,grid",
        help="Comma-separated broadphase backends to benchmark: quadtree, grid (grid-only: --backends grid)",
    )
    ap.add_argument(
        "--counts",
        default=None,
        help="Comma-separated entity counts (overrides default 100,150,...), e.g. 150,200,300",
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
    simple_swarm_neighbor_limits = _parse_int_list(args.swarm_neighbors)
    if not simple_swarm_neighbor_limits:
        simple_swarm_neighbor_limits = [4]
    grass_wind_modes = [m.strip() for m in args.grass_wind_modes.split(",") if m.strip()]
    if not grass_wind_modes:
        grass_wind_modes = ["legacy_tile"]
    grass_disturbance_modes = []
    for mode in args.grass_disturbance.split(","):
        token = mode.strip().lower()
        if token in {"on", "true", "1", "yes"}:
            grass_disturbance_modes.append(True)
        elif token in {"off", "false", "0", "no"}:
            grass_disturbance_modes.append(False)
    if not grass_disturbance_modes:
        grass_disturbance_modes = [True]
    counts_override = _parse_int_list(args.counts) if args.counts else None
    raise SystemExit(
        run_matrix(
            auto_seconds=args.seconds,
            warmup_seconds=args.warmup,
            counts=counts_override,
            grid_cell_sizes=grid_cell_sizes,
            cap_sweep=args.cap_sweep,
            cap_values=cap_vals,
            enemy_type=args.enemy,
            enemy_mix=args.enemy_mix,
            backends=backends,
            collision_modes=collision_modes,
            simple_swarm_neighbor_limits=simple_swarm_neighbor_limits,
            grass_enabled=args.grass,
            grass_wind_modes=grass_wind_modes,
            grass_disturbance_modes=grass_disturbance_modes,
            layout_dir=args.layout_dir,
        )
    )
