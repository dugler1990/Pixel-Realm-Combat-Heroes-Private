import csv
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List

from Settings import (
    BENCHMARK_AUTO_RUN_SECONDS,
    BENCHMARK_BROADPHASE_BACKEND,
    BENCHMARK_DETERMINISTIC_SPAWN,
    BENCHMARK_ENABLED,
    BENCHMARK_ENEMY_TYPE,
    BENCHMARK_ENTITY_COUNT,
    BENCHMARK_METRICS_CSV_PATH,
    BENCHMARK_METRICS_ENABLED,
    BENCHMARK_METRICS_LOG_EVERY_SEC,
    BENCHMARK_PUSHBACK_CAP_ENABLED,
    BENCHMARK_PUSHBACK_FLOOR_ENABLED,
    BENCHMARK_PUSHBACK_MAX_CAP,
    BENCHMARK_PUSHBACK_MIN_THRESHOLD,
    BENCHMARK_WARMUP_SECONDS,
    BENCHMARK_SEED,
)
from game_logging import get_debug_logger


_bench_log = get_debug_logger("game_flow")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return str(raw) if raw is not None else default


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


@dataclass
class BenchmarkMetrics:
    frame_times_ms: List[float] = field(default_factory=list)
    broadphase_queries: int = 0
    broadphase_candidates: int = 0
    resolved_collisions: int = 0
    maintenance_insert: int = 0
    maintenance_remove: int = 0
    maintenance_upsert: int = 0

    def reset(self):
        self.frame_times_ms.clear()
        self.broadphase_queries = 0
        self.broadphase_candidates = 0
        self.resolved_collisions = 0
        self.maintenance_insert = 0
        self.maintenance_remove = 0
        self.maintenance_upsert = 0

    def record_frame(self, dt_seconds: float):
        self.frame_times_ms.append(max(0.0, dt_seconds) * 1000.0)

    def record_query(self, candidates: int):
        self.broadphase_queries += 1
        self.broadphase_candidates += max(0, int(candidates))

    def record_collision_resolved(self):
        self.resolved_collisions += 1

    def record_maintenance(self, op: str):
        if op == "insert":
            self.maintenance_insert += 1
        elif op == "remove":
            self.maintenance_remove += 1
        elif op == "upsert":
            self.maintenance_upsert += 1

    def snapshot(self) -> Dict[str, float]:
        frame_count = len(self.frame_times_ms)
        total_ms = sum(self.frame_times_ms)
        avg_frame_ms = (total_ms / frame_count) if frame_count else 0.0
        avg_fps = 1000.0 / avg_frame_ms if avg_frame_ms > 0 else 0.0
        return {
            "frames": frame_count,
            "avg_frame_ms": avg_frame_ms,
            "avg_fps": avg_fps,
            "p95_frame_ms": _percentile(self.frame_times_ms, 95.0),
            "broadphase_queries": self.broadphase_queries,
            "candidate_collisions": self.broadphase_candidates,
            "resolved_collisions": self.resolved_collisions,
            "maintenance_insert": self.maintenance_insert,
            "maintenance_remove": self.maintenance_remove,
            "maintenance_upsert": self.maintenance_upsert,
        }


@dataclass
class BenchmarkRuntimeState:
    enabled: bool = BENCHMARK_ENABLED
    entity_count: int = BENCHMARK_ENTITY_COUNT
    seed: int = BENCHMARK_SEED
    deterministic_spawn: bool = BENCHMARK_DETERMINISTIC_SPAWN
    broadphase_backend: str = BENCHMARK_BROADPHASE_BACKEND
    pushback_floor_enabled: bool = BENCHMARK_PUSHBACK_FLOOR_ENABLED
    pushback_min_threshold: float = BENCHMARK_PUSHBACK_MIN_THRESHOLD
    pushback_cap_enabled: bool = BENCHMARK_PUSHBACK_CAP_ENABLED
    pushback_max_cap: float = BENCHMARK_PUSHBACK_MAX_CAP
    metrics_enabled: bool = BENCHMARK_METRICS_ENABLED
    metrics_log_every_sec: float = BENCHMARK_METRICS_LOG_EVERY_SEC
    auto_run_seconds: float = BENCHMARK_AUTO_RUN_SECONDS
    metrics_csv_path: str = BENCHMARK_METRICS_CSV_PATH
    run_label: str = "manual"
    run_started_at: float = 0.0
    last_metrics_log_at: float = 0.0
    matrix_enabled: bool = False
    matrix_counts: List[int] = field(default_factory=lambda: [100, 150, 200, 250, 300])
    matrix_backends: List[str] = field(default_factory=lambda: ["quadtree", "grid"])
    grid_cell_sizes: List[int] = field(default_factory=lambda: [150, 300, 450])
    grid_cell_size: int = 300
    matrix_prefix: str = "matrix"
    matrix_cap_sweep: bool = False
    matrix_cap_sweep_values: List[float] = field(default_factory=lambda: [8.0, 12.0, 16.0])
    enemy_type: str = BENCHMARK_ENEMY_TYPE
    matrix_cases: List[Dict[str, object]] = field(default_factory=list)
    matrix_case_index: int = -1
    warmup_seconds: float = BENCHMARK_WARMUP_SECONDS
    warmup_started_at: float = 0.0
    case_phase: str = "setup"  # setup -> warmup -> measure -> complete
    metrics: BenchmarkMetrics = field(default_factory=BenchmarkMetrics)

    def begin_run(self, run_label: str = ""):
        if run_label:
            self.run_label = run_label
        now = time.time()
        self.run_started_at = now
        self.last_metrics_log_at = now
        self.metrics.reset()
        self.case_phase = "measure"

    def begin_warmup(self):
        self.warmup_started_at = time.time()
        self.case_phase = "warmup"

    def warmup_elapsed(self) -> bool:
        if self.case_phase != "warmup":
            return False
        return (time.time() - self.warmup_started_at) >= max(0.0, self.warmup_seconds)

    def maybe_log_metrics(self):
        if not (self.enabled and self.metrics_enabled):
            return
        now = time.time()
        if (now - self.last_metrics_log_at) < self.metrics_log_every_sec:
            return
        self.last_metrics_log_at = now
        snap = self.metrics.snapshot()
        _bench_log.debug(
            "BENCHMARK_METRICS run=%s backend=%s floor=%s cap=%s frames=%s avg_fps=%.2f avg_ms=%.2f p95_ms=%.2f queries=%s candidates=%s resolved=%s maint(i/r/u)=%s/%s/%s",
            self.run_label,
            self.broadphase_backend,
            self.pushback_floor_enabled,
            self.pushback_cap_enabled,
            snap["frames"],
            snap["avg_fps"],
            snap["avg_frame_ms"],
            snap["p95_frame_ms"],
            snap["broadphase_queries"],
            snap["candidate_collisions"],
            snap["resolved_collisions"],
            snap["maintenance_insert"],
            snap["maintenance_remove"],
            snap["maintenance_upsert"],
        )

    def should_auto_stop(self) -> bool:
        if not self.enabled or self.auto_run_seconds <= 0:
            return False
        return (time.time() - self.run_started_at) >= self.auto_run_seconds

    def write_summary_row(self) -> Dict[str, float]:
        snap = self.metrics.snapshot()
        row = {
            "run_label": self.run_label,
            "enemy_type": self.enemy_type,
            "backend": self.broadphase_backend,
            "grid_cell_size": self.grid_cell_size if self.broadphase_backend == "grid" else "",
            "entity_count": self.entity_count,
            "seed": self.seed,
            "pushback_floor_enabled": self.pushback_floor_enabled,
            "pushback_min_threshold": self.pushback_min_threshold,
            "pushback_cap_enabled": self.pushback_cap_enabled,
            "pushback_max_cap": self.pushback_max_cap,
            **snap,
        }

        csv_path = os.path.normpath(os.path.join(os.path.dirname(__file__), self.metrics_csv_path))
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        file_exists = os.path.exists(csv_path) and os.path.getsize(csv_path) > 0
        new_row = {k: row[k] for k in row}

        if not file_exists:
            fieldnames = list(new_row.keys())
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerow(new_row)
            _bench_log.debug("BENCHMARK_SUMMARY_WRITTEN path=%s row=%s", csv_path, row)
            return row

        with open(csv_path, "r", encoding="utf-8", newline="") as f:
            old_reader = csv.DictReader(f)
            old_fieldnames = list(old_reader.fieldnames or [])
            old_rows = list(old_reader)

        fieldnames = list(old_fieldnames)
        for k in new_row.keys():
            if k not in fieldnames:
                fieldnames.append(k)

        out_row = {k: new_row.get(k, "") for k in fieldnames}

        if fieldnames != old_fieldnames:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for d in old_rows:
                    writer.writerow({k: d.get(k, "") for k in fieldnames})
                writer.writerow(out_row)
        else:
            with open(csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writerow(out_row)
        _bench_log.debug("BENCHMARK_SUMMARY_WRITTEN path=%s row=%s", csv_path, row)
        return row

    def _build_matrix_cases(self):
        """Populate matrix_cases for the benchmark matrix.

        Modes:
        - When matrix_cap_sweep is False:
            * "off"  -> floor=False, cap=False
            * "on"   -> floor=True,  cap=True (max_cap = default)
        - When matrix_cap_sweep is True:
            * "off"        -> floor=False, cap=False  (baseline)
            * "floor_only" -> floor=True,  cap=False  (isolated floor)
            * "cap{v}"     -> floor=False, cap=True,  max_cap=v   (isolated cap)
            * "floor_cap{v}" -> floor=True, cap=True, max_cap=v   (combined)
        """
        self.matrix_cases = []

        if self.matrix_cap_sweep:
            variants: List[tuple] = []
            # Baseline: no floor, no cap.
            variants.append(("off", False, False, None))
            # Floor-only: floor on, cap off.
            variants.append(("floor_only", True, False, None))
            # Cap-only and floor+cap variants for each configured cap value.
            for v in self.matrix_cap_sweep_values:
                # Cap-only
                cap_label = f"cap{int(v)}" if float(v).is_integer() else f"cap{v}"
                variants.append((cap_label, False, True, float(v)))
                # Floor + cap
                both_label = f"floor_cap{int(v)}" if float(v).is_integer() else f"floor_cap{v}"
                variants.append((both_label, True, True, float(v)))
        else:
            variants = [
                ("off", False, False, None),
                ("on", True, True, None),
            ]

        for count in self.matrix_counts:
            for backend in self.matrix_backends:
                for toggle_name, floor_enabled, cap_enabled, max_cap in variants:
                    if str(backend) == "grid":
                        for cell_size in self.grid_cell_sizes:
                            case: Dict[str, object] = {
                                "entity_count": int(count),
                                "backend": str(backend),
                                "toggle_name": toggle_name,
                                "pushback_floor_enabled": floor_enabled,
                                "pushback_cap_enabled": cap_enabled,
                                "grid_cell_size": int(cell_size),
                            }
                            if max_cap is not None:
                                case["pushback_max_cap"] = max_cap
                            self.matrix_cases.append(case)
                    else:
                        case = {
                            "entity_count": int(count),
                            "backend": str(backend),
                            "toggle_name": toggle_name,
                            "pushback_floor_enabled": floor_enabled,
                            "pushback_cap_enabled": cap_enabled,
                            "grid_cell_size": None,
                        }
                        if max_cap is not None:
                            case["pushback_max_cap"] = max_cap
                        self.matrix_cases.append(case)
        self.matrix_case_index = -1

    def begin_matrix(self):
        self._build_matrix_cases()

    def start_next_matrix_case(self):
        if not self.matrix_cases:
            self._build_matrix_cases()
        self.matrix_case_index += 1
        if self.matrix_case_index >= len(self.matrix_cases):
            return None

        case = self.matrix_cases[self.matrix_case_index]
        self.entity_count = int(case["entity_count"])
        self.broadphase_backend = str(case["backend"])
        self.pushback_floor_enabled = bool(case["pushback_floor_enabled"])
        self.pushback_cap_enabled = bool(case["pushback_cap_enabled"])
        if "pushback_max_cap" in case and case["pushback_max_cap"] is not None:
            self.pushback_max_cap = float(case["pushback_max_cap"])
        else:
            self.pushback_max_cap = BENCHMARK_PUSHBACK_MAX_CAP
        case_cell_size = case.get("grid_cell_size", None)
        if case_cell_size is None:
            self.grid_cell_size = self.grid_cell_sizes[0] if self.grid_cell_sizes else 300
        else:
            self.grid_cell_size = int(case_cell_size)
        self.run_label = (
            f"{self.matrix_prefix}_{self.entity_count}_{self.broadphase_backend}_"
            f"cell{self.grid_cell_size}_{case['toggle_name']}"
        )
        self.case_phase = "setup"
        return case

    def matrix_progress(self):
        total = len(self.matrix_cases)
        current = self.matrix_case_index + 1
        return current, total


def _env_float_list(name: str, default: List[float]) -> List[float]:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return list(default)
    out = []
    for token in str(raw).split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(float(token))
        except ValueError:
            pass
    return out or list(default)


def _env_int_list(name: str, default: List[int]) -> List[int]:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return list(default)
    out = []
    for token in str(raw).split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError:
            pass
    return out or list(default)


def _env_str_list(name: str, default: List[str]) -> List[str]:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return list(default)
    out = [token.strip() for token in str(raw).split(",") if token.strip()]
    return out or list(default)


BENCHMARK_RUNTIME = BenchmarkRuntimeState(
    enabled=_env_bool("PRCH_BENCHMARK_ENABLED", BENCHMARK_ENABLED),
    entity_count=_env_int("PRCH_BENCHMARK_ENTITY_COUNT", BENCHMARK_ENTITY_COUNT),
    seed=_env_int("PRCH_BENCHMARK_SEED", BENCHMARK_SEED),
    deterministic_spawn=_env_bool(
        "PRCH_BENCHMARK_DETERMINISTIC_SPAWN", BENCHMARK_DETERMINISTIC_SPAWN
    ),
    broadphase_backend=_env_str("PRCH_BENCHMARK_BROADPHASE_BACKEND", BENCHMARK_BROADPHASE_BACKEND),
    pushback_floor_enabled=_env_bool(
        "PRCH_BENCHMARK_PUSHBACK_FLOOR_ENABLED", BENCHMARK_PUSHBACK_FLOOR_ENABLED
    ),
    pushback_min_threshold=_env_float(
        "PRCH_BENCHMARK_PUSHBACK_MIN_THRESHOLD", BENCHMARK_PUSHBACK_MIN_THRESHOLD
    ),
    pushback_cap_enabled=_env_bool(
        "PRCH_BENCHMARK_PUSHBACK_CAP_ENABLED", BENCHMARK_PUSHBACK_CAP_ENABLED
    ),
    pushback_max_cap=_env_float(
        "PRCH_BENCHMARK_PUSHBACK_MAX_CAP", BENCHMARK_PUSHBACK_MAX_CAP
    ),
    metrics_enabled=_env_bool("PRCH_BENCHMARK_METRICS_ENABLED", BENCHMARK_METRICS_ENABLED),
    metrics_log_every_sec=_env_float(
        "PRCH_BENCHMARK_METRICS_LOG_EVERY_SEC", BENCHMARK_METRICS_LOG_EVERY_SEC
    ),
    auto_run_seconds=_env_float("PRCH_BENCHMARK_AUTO_RUN_SECONDS", BENCHMARK_AUTO_RUN_SECONDS),
    warmup_seconds=_env_float("PRCH_BENCHMARK_WARMUP_SECONDS", BENCHMARK_WARMUP_SECONDS),
    metrics_csv_path=_env_str("PRCH_BENCHMARK_METRICS_CSV_PATH", BENCHMARK_METRICS_CSV_PATH),
    run_label=_env_str("PRCH_BENCHMARK_RUN_LABEL", "manual"),
    matrix_enabled=_env_bool("PRCH_BENCHMARK_MATRIX_ENABLED", False),
    matrix_counts=_env_int_list("PRCH_BENCHMARK_MATRIX_COUNTS", [100, 150, 200, 250, 300]),
    matrix_backends=_env_str_list("PRCH_BENCHMARK_MATRIX_BACKENDS", ["quadtree", "grid"]),
    grid_cell_sizes=_env_int_list("PRCH_BENCHMARK_GRID_CELL_SIZES", [150, 300, 450]),
    matrix_prefix=_env_str("PRCH_BENCHMARK_MATRIX_PREFIX", "matrix"),
    matrix_cap_sweep=_env_bool("PRCH_BENCHMARK_MATRIX_CAP_SWEEP", False),
    matrix_cap_sweep_values=_env_float_list(
        "PRCH_BENCHMARK_MATRIX_CAP_VALUES", [8.0, 12.0, 16.0]
    ),
    enemy_type=_env_str("PRCH_BENCHMARK_ENEMY_TYPE", BENCHMARK_ENEMY_TYPE),
)
