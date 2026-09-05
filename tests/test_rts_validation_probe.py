"""RTS validation probe status and terrain scenario gating."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Code"))

from rts_validation_driver import RtsValidationDriver  # noqa: E402
from rts_validation_runtime import RtsValidationRuntime  # noqa: E402


def test_probe_counts_as_pass_for_ci(tmp_path):
    runtime = RtsValidationRuntime(output_path=str(tmp_path / "out.json"))
    runtime.record(
        "terrain_slope_speed",
        False,
        "still unimplemented, slope_mult=1.0",
        status="probe",
    )
    assert runtime.scenarios[0].status == "probe"
    assert runtime.scenarios[0].passed is True
    assert runtime.all_passed is True
    payload = runtime.write_results()
    assert payload["ok"] is True
    assert payload["scenarios"][0]["status"] == "probe"


def test_fail_still_fails_ci(tmp_path):
    runtime = RtsValidationRuntime(output_path=str(tmp_path / "out.json"))
    runtime.record("terrain_height_sample", False, "void was 0")
    assert runtime.all_passed is False
    assert runtime.scenarios[0].status == "fail"


def test_empty_filter_excludes_terrain():
    from rts_validation_runtime import RTS_VALIDATION_RUNTIME

    previous = list(RTS_VALIDATION_RUNTIME.scenario_filter)
    try:
        RTS_VALIDATION_RUNTIME.scenario_filter = []
        names = RtsValidationDriver()._filtered_names()
        assert names == list(RtsValidationDriver.DEFAULT_SCENARIO_NAMES)
        assert not any(n in RtsValidationDriver.TERRAIN_SCENARIO_NAMES for n in names)
    finally:
        RTS_VALIDATION_RUNTIME.scenario_filter = previous


def test_literal_all_excludes_terrain():
    from rts_validation_runtime import RTS_VALIDATION_RUNTIME

    previous = list(RTS_VALIDATION_RUNTIME.scenario_filter)
    try:
        RTS_VALIDATION_RUNTIME.scenario_filter = ["all"]
        names = RtsValidationDriver()._filtered_names()
        assert names == list(RtsValidationDriver.DEFAULT_SCENARIO_NAMES)
        assert "terrain_height_sample" not in names
    finally:
        RTS_VALIDATION_RUNTIME.scenario_filter = previous


def test_explicit_terrain_name_is_included():
    from rts_validation_runtime import RTS_VALIDATION_RUNTIME

    previous = list(RTS_VALIDATION_RUNTIME.scenario_filter)
    try:
        RTS_VALIDATION_RUNTIME.scenario_filter = ["terrain_height_sample"]
        names = RtsValidationDriver()._filtered_names()
        assert names == ["terrain_height_sample"]
    finally:
        RTS_VALIDATION_RUNTIME.scenario_filter = previous
