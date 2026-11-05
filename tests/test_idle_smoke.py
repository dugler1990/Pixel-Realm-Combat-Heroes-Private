"""The fluid solver runs only while a cloud is fading, then the draws stop too."""
import math
import sys
from pathlib import Path
from unittest.mock import Mock

CODE_DIR = Path(__file__).resolve().parents[1] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from gpu_fluid_smoke import GpuFluidSmoke  # noqa: E402


def _smoke():
    smoke = GpuFluidSmoke(backend=None)

    def _init():
        smoke._ready = True
        return True

    smoke._try_init = Mock(side_effect=_init)
    smoke._gl_step = Mock()
    smoke._draw_display = Mock()
    smoke._programs["display_ground"] = "ground"
    smoke._programs["display_rise"] = "rise"
    return smoke


def _step(smoke, n=1, view=(800, 600)):
    for _ in range(n):
        smoke.step(1 / 30, None, (0, 0), view)


def test_fade_steps_is_the_first_step_at_or_under_fade_stop():
    smoke = GpuFluidSmoke(backend=None)
    expected = math.ceil(math.log(smoke.FADE_STOP) / math.log(smoke.den_dissipation))
    assert smoke.fade_steps == expected
    assert smoke.den_dissipation ** smoke.fade_steps <= smoke.FADE_STOP
    assert smoke.den_dissipation ** (smoke.fade_steps - 1) > smoke.FADE_STOP


def test_idle_step_does_not_init_or_solve():
    smoke = _smoke()
    _step(smoke)
    smoke._gl_step.assert_not_called()
    smoke._try_init.assert_not_called()
    assert smoke._show is False


def test_on_screen_puff_runs_for_fade_steps_then_stops():
    smoke = _smoke()
    smoke.queue_splat((100, 100))
    _step(smoke, smoke.fade_steps)
    assert smoke._gl_step.call_count == smoke.fade_steps
    assert smoke._show is True
    _step(smoke)
    assert smoke._gl_step.call_count == smoke.fade_steps
    assert smoke._show is False


def test_puff_during_the_fade_restarts_the_count():
    smoke = _smoke()
    smoke.queue_splat((100, 100))
    _step(smoke, 10)
    smoke.queue_splat((120, 120))
    smoke._gl_step.reset_mock()
    _step(smoke, smoke.fade_steps)
    assert smoke._gl_step.call_count == smoke.fade_steps
    _step(smoke)
    assert smoke._gl_step.call_count == smoke.fade_steps


def test_offscreen_puff_does_not_start_the_solver():
    smoke = _smoke()
    smoke.queue_splat((5000, 5000))
    _step(smoke)
    smoke._gl_step.assert_not_called()
    smoke._try_init.assert_not_called()


def test_bad_view_keeps_a_queued_puff():
    smoke = _smoke()
    smoke.queue_splat((100, 100))
    _step(smoke, view=(0, 0))
    smoke._gl_step.assert_not_called()
    _step(smoke)
    smoke._gl_step.assert_called_once()


def test_draws_follow_the_frame_that_wrote_buffers():
    smoke = _smoke()
    _step(smoke)
    smoke.draw_ground()
    smoke.draw_rise()
    smoke._draw_display.assert_not_called()

    smoke.queue_splat((100, 100))
    _step(smoke)
    smoke.draw_ground()
    smoke.draw_rise()
    assert smoke._draw_display.call_count == 2

    _step(smoke, smoke.fade_steps)
    assert smoke._ready is True
    assert smoke._show is False
    smoke._draw_display.reset_mock()
    smoke.draw_ground()
    smoke.draw_rise()
    smoke._draw_display.assert_not_called()
