"""Fog circle math — antipode, sectors, inset."""

import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from ice_fog.geometry import FogCircle, antipode_inside, sector_of


def test_antipode_east_goes_west():
    c = FogCircle(200, 200, 120)
    x, y = antipode_inside(c, 320, 200, inset=8)
    assert x < c.cx
    assert y == pytest.approx(c.cy)
    assert c.is_inside(x, y)
    assert math.hypot(x - c.cx, y - c.cy) == pytest.approx(112)


def test_inset_stays_strictly_inside():
    c = FogCircle(0, 0, 100)
    x, y = antipode_inside(c, 100, 0, inset=10)
    assert c.is_inside(x, y)
    assert math.hypot(x, y) < 100


def test_sector_quadrants():
    c = FogCircle(0, 0, 50)
    assert sector_of(c, 10, 0) == "E"
    assert sector_of(c, 0, -10) == "N"
    assert sector_of(c, -10, 0) == "W"
    assert sector_of(c, 0, 10) == "S"
