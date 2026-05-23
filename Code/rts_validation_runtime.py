"""Env-driven runtime for in-game RTS validation (Main2 subprocess)."""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


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


def _env_str_list(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    if not raw or str(raw).strip().lower() == "all":
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip()]


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    details: str
    ms: float = 0.0


@dataclass
class RtsValidationRuntime:
    enabled: bool = False
    layout_dir: str = "../levels/tmx"
    scenario_filter: List[str] = field(default_factory=list)
    max_seconds: float = 30.0
    output_path: str = "../logs/rts_validation_latest.json"
    fast_mode: bool = True
    visible_mode: bool = False
    hold_seconds: float = 0.0
    overlay_state: Dict[str, Any] = field(default_factory=dict)
    scenarios: List[ScenarioResult] = field(default_factory=list)
    shutdown_requested: bool = False
    shutdown_exit_code: int = 0

    @property
    def overlay_enabled(self) -> bool:
        return self.visible_mode

    def wants_scenario(self, name: str) -> bool:
        if not self.scenario_filter:
            return True
        return name in self.scenario_filter

    def set_overlay(self, lines: List[str], phase: str = "RUNNING"):
        if not self.overlay_enabled:
            return
        self.overlay_state = {"lines": list(lines), "phase": phase}

    def record(self, name: str, passed: bool, details: str, ms: float = 0.0):
        self.scenarios.append(
            ScenarioResult(name=name, passed=passed, details=details, ms=ms)
        )
        status = "PASS" if passed else "FAIL"
        print(f"[RTS_VAL] {name}: {status} ({details})", flush=True)

    @property
    def all_passed(self) -> bool:
        return bool(self.scenarios) and all(s.passed for s in self.scenarios)

    def write_results(self) -> dict:
        code_dir = os.path.dirname(os.path.abspath(__file__))
        out_path = self.output_path
        if not os.path.isabs(out_path):
            out_path = os.path.normpath(os.path.join(code_dir, out_path))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        payload = {
            "ok": self.all_passed,
            "layout_dir": self.layout_dir,
            "fast_mode": self.fast_mode,
            "visible_mode": self.visible_mode,
            "hold_seconds": self.hold_seconds,
            "max_seconds_fallback": self.max_seconds,
            "scenarios": [
                {
                    "name": s.name,
                    "passed": s.passed,
                    "details": s.details,
                    "ms": round(s.ms, 2),
                }
                for s in self.scenarios
            ],
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        return payload

    def request_shutdown(self, exit_code: int = 0):
        self.shutdown_requested = True
        self.shutdown_exit_code = exit_code


RTS_VALIDATION_RUNTIME = RtsValidationRuntime(
    enabled=_env_bool("PRCH_RTS_VALIDATION_ENABLED", False),
    layout_dir=_env_str("PRCH_RTS_VALIDATION_LAYOUT_DIR", "../levels/tmx"),
    scenario_filter=_env_str_list("PRCH_RTS_VALIDATION_SCENARIOS", "all"),
    max_seconds=_env_float("PRCH_RTS_VALIDATION_MAX_SECONDS", 30.0),
    output_path=_env_str(
        "PRCH_RTS_VALIDATION_OUTPUT", "../logs/rts_validation_latest.json"
    ),
    fast_mode=_env_bool("PRCH_RTS_VALIDATION_FAST", True),
    visible_mode=_env_bool("PRCH_RTS_VALIDATION_VISIBLE", False),
    hold_seconds=_env_float("PRCH_RTS_VALIDATION_HOLD_SECONDS", 0.0),
)
