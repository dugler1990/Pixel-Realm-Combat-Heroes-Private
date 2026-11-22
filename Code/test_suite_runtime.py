"""Env-driven runtime for in-game test suite (Main2 subprocess, test_suite.py).

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


class TestSuiteRuntime(RtsValidationRuntime):
    TAG = "COMBAT_VAL"


TEST_SUITE_RUNTIME = TestSuiteRuntime(
    enabled=_env_bool("PRCH_TEST_SUITE_ENABLED", False),
    layout_dir=_env_str("PRCH_TEST_SUITE_LAYOUT_DIR", "../levels/benchmark"),
    scenario_filter=_env_str_list("PRCH_TEST_SUITE_SCENARIOS", "all"),
    max_seconds=_env_float("PRCH_TEST_SUITE_MAX_SECONDS", 30.0),
    output_path=_env_str("PRCH_TEST_SUITE_OUTPUT", "../logs/test_suite_latest.json"),
    fast_mode=_env_bool("PRCH_TEST_SUITE_FAST", True),
    visible_mode=_env_bool("PRCH_TEST_SUITE_VISIBLE", False),
    hold_seconds=_env_float("PRCH_TEST_SUITE_HOLD_SECONDS", 0.0),
)
# The hero's mesh pack (PlayerSelectionDict.json "mesh_pack").
TEST_SUITE_MESH_PACK = _env_str("PRCH_TEST_SUITE_MESH_PACK", "barb")
