"""The heat network solver (temperature step 1): exact curves, crossings and areas, no pygame."""
import math
import sys
from pathlib import Path

import pytest

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from heat_network import solve  # noqa: E402


def _numeric_area(curve, i, line, t0, t1, above=True, steps=200_000):
    dt = (t1 - t0) / steps
    sign = 1.0 if above else -1.0
    total = 0.0
    for n in range(steps):
        v = sign * (curve.layer_at(i, t0 + (n + 0.5) * dt) - line)
        if v > 0:
            total += v * dt
    return total


def _plate_on_skin():
    """Skin (capacity 1, body heater k 0.05 at 0) under a hot plate (capacity 3, ice air
    k 0.02 at -30), joined by a link 0.04: the skin warms from the plate, then cools."""
    return solve(start=[-20.0, 60.0], capacity=[1.0, 3.0],
                 pull=[(0.05, 0.0), (0.02, 0.02 * -30.0)], links=[(0, 1, 0.04)])


def test_one_layer_is_the_plain_exponential():
    curve = solve([12.0], [2.0], [(0.5, 0.5 * -4.0)])
    for t in (0.0, 1.0, 7.5, 60.0):
        assert curve.layer_at(0, t) == pytest.approx(-4.0 + 16.0 * math.exp(-0.25 * t))


def test_the_steady_state_is_the_weighted_pull():
    sources = [(0.01, -30.0), (0.05, 0.0), (0.2, -10.0)]   # air, body, a hold
    k = sum(s for s, _t in sources)
    curve = solve([0.0], [1.0], [(k, sum(s * t for s, t in sources))])
    assert curve.layer_at(0, 1e6) == pytest.approx(sum(s * t for s, t in sources) / k)


def test_a_link_alone_keeps_the_heat_and_evens_it_out():
    curve = solve([20.0, -10.0], [1.0, 3.0], [(0.0, 0.0), (0.0, 0.0)], links=[(0, 1, 0.3)])
    for t in (0.0, 2.0, 30.0):
        a, b = curve.at(t)
        assert 1.0 * a + 3.0 * b == pytest.approx(20.0 - 30.0)
    a, b = curve.at(1e4)
    assert a == pytest.approx(-2.5) and b == pytest.approx(-2.5)


def test_a_layer_with_nothing_on_it_keeps_its_warmth():
    curve = solve([7.0, 3.0], [1.0, 1.0], [(0.1, 0.0), (0.0, 0.0)])
    assert curve.layer_at(1, 500.0) == pytest.approx(3.0)
    assert curve.layer_at(0, 500.0) == pytest.approx(0.0, abs=1e-6)


def test_crossings_are_where_the_curve_meets_the_line():
    curve = _plate_on_skin()
    found = curve.crossings(0, 5.0, 0.0, 300.0)
    assert len(found) == 2   # up past 5 as the plate warms it, back down as both cool
    for t in found:   # found to 0.1 ms: the line is on one side just before, the other just after
        assert (curve.layer_at(0, t - 1e-4) - 5.0) * (curve.layer_at(0, t + 1e-4) - 5.0) < 0
    dense = [curve.layer_at(0, 0.05 * n) - 5.0 for n in range(6001)]
    changes = sum(1 for a, b in zip(dense, dense[1:]) if a * b < 0)
    assert changes == len(found)


def test_the_area_past_a_line_matches_a_fine_sum():
    curve = _plate_on_skin()
    assert curve.area_past(0, 5.0, 0.0, 300.0) == pytest.approx(
        _numeric_area(curve, 0, 5.0, 0.0, 300.0), rel=1e-4)
    assert curve.area_past(0, -12.0, 0.0, 3000.0, above=False) == pytest.approx(
        _numeric_area(curve, 0, -12.0, 0.0, 3000.0, above=False), rel=1e-4)
    assert curve.area_past(0, 5.0, 10.0, 10.0) == 0.0


def test_bad_input_is_an_error():
    with pytest.raises(ValueError):
        solve([0.0], [0.0], [(1.0, 0.0)])
    with pytest.raises(ValueError):
        solve([0.0], [1.0], [(-1.0, 0.0)])
    with pytest.raises(ValueError):
        solve([0.0, 0.0], [1.0], [(1.0, 0.0)])


def test_two_layers_by_hand_match_the_general_solve():
    from heat_network import _many
    args = ([-20.0, 60.0], [1.0, 3.0], [(0.05, 0.0), (0.02, -0.6)])
    by_hand = solve(*args, links=[(0, 1, 0.04)])
    general = _many(*args, [(0, 1, 0.04)])
    for t in (0.0, 3.0, 40.0, 400.0):
        assert by_hand.at(t) == pytest.approx(general.at(t))


def test_first_crossing_is_the_earliest_of_its_lines():
    curve = _plate_on_skin()
    lines = (5.0, 2.0, -10.0)
    first = curve.first_crossing(0, lines, 0.0, 600.0)
    every = sorted(t for line in lines for t in curve.crossings(0, line, 0.0, 600.0))
    assert first == pytest.approx(every[0], abs=1e-4)
    assert curve.first_crossing(0, (500.0,), 0.0, 600.0) is None   # out of reach: no search
