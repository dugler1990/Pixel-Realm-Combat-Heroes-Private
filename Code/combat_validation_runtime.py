"""Env-driven runtime for in-game combat validation (Main2 subprocess, combat_validation.py).

The same results, overlay and shutdown as the RTS validation (rts_validation_runtime), in the
benchmark arena (levels/benchmark: black floor, magenta walls) with a mesh hero.
"""

from rts_validation_runtime import (
    RtsValidationRuntime,
    _env_bool,
    _env_float,
    _env_str,
    _env_str_list,
)


class CombatValidationRuntime(RtsValidationRuntime):
    TAG = "COMBAT_VAL"


COMBAT_VALIDATION_RUNTIME = CombatValidationRuntime(
    enabled=_env_bool("PRCH_COMBAT_VALIDATION_ENABLED", False),
    layout_dir=_env_str("PRCH_COMBAT_VALIDATION_LAYOUT_DIR", "../levels/benchmark"),
    scenario_filter=_env_str_list("PRCH_COMBAT_VALIDATION_SCENARIOS", "all"),
    max_seconds=_env_float("PRCH_COMBAT_VALIDATION_MAX_SECONDS", 30.0),
    output_path=_env_str("PRCH_COMBAT_VALIDATION_OUTPUT", "../logs/combat_validation_latest.json"),
    fast_mode=_env_bool("PRCH_COMBAT_VALIDATION_FAST", True),
    visible_mode=_env_bool("PRCH_COMBAT_VALIDATION_VISIBLE", False),
    hold_seconds=_env_float("PRCH_COMBAT_VALIDATION_HOLD_SECONDS", 0.0),
)
# The hero's mesh pack (PlayerSelectionDict.json "mesh_pack").
COMBAT_VALIDATION_MESH_PACK = _env_str("PRCH_COMBAT_VALIDATION_MESH_PACK", "barb")
