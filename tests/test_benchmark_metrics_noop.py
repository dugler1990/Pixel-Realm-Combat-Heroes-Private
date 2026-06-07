import os
import sys
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from benchmark_broadphase import (  # noqa: E402
    _RECORD_METRICS,
    set_metrics_recording,
)


def test_metrics_recording_defaults_false():
    assert _RECORD_METRICS is False


def test_set_metrics_recording_toggles_flag():
    import benchmark_broadphase as bb

    set_metrics_recording(True)
    try:
        assert bb._RECORD_METRICS is True
    finally:
        set_metrics_recording(False)


def test_record_benchmark_query_noop_when_disabled():
    import benchmark_broadphase as bb

    set_metrics_recording(False)
    with mock.patch.object(bb.BENCHMARK_RUNTIME.metrics, "record_query") as record_query:
        bb._record_benchmark_query(5)
        record_query.assert_not_called()

    set_metrics_recording(True)
    try:
        with mock.patch.object(bb.BENCHMARK_RUNTIME.metrics, "record_query") as record_query:
            bb._record_benchmark_query(5)
            record_query.assert_called_once_with(5)
    finally:
        set_metrics_recording(False)
