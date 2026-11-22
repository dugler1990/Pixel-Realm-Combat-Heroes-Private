"""The physical rule, row for row from physical_resolve.plan.md (damage chunk 5). No display."""
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from damage_data import LayerDef, body  # noqa: E402
from damage_rules import BRUISE_SCALE, landed, physical  # noqa: E402

HIDE = body("barb").natural
PLATE = LayerDef("plate", stopping_power=40, absorb=0.15)
GAMBESON = LayerDef("gambeson", stopping_power=5, absorb=0.5)
DEMON = body("demon").natural
PLATE_STACK = (PLATE, HIDE)
NAKED = (HIDE,)


def _hit(delivery, damage, pen, force, layers):
    result = physical(delivery, damage, pen, force, layers)
    return landed(result), result


def test_bruise_scale_is_the_knob():
    assert BRUISE_SCALE == 0.05


def test_dart_stops_on_plate_and_wounds_skin():
    plate, stopped = _hit("pierce", 4, 12, 2, PLATE_STACK)
    skin, through = _hit("pierce", 4, 12, 2, NAKED)
    assert plate == 0 and stopped.stopped_at is PLATE and stopped.reached_flesh is False
    assert skin == 4 and through.reached_flesh is True and through.stopped_at is None


def test_arrow_and_spear_stop_on_plate():
    assert _hit("pierce", 6, 30, 4, PLATE_STACK)[0] == 0
    assert _hit("pierce", 6, 30, 4, NAKED)[0] == 6
    assert _hit("pierce", 6, 25, 10, PLATE_STACK)[0] == 0
    assert _hit("pierce", 6, 25, 10, NAKED)[0] == 6


def test_sword_is_a_speck_on_plate_and_full_on_skin():
    assert _hit("pierce", 15, 20, 15, PLATE_STACK)[0] == 1
    assert _hit("pierce", 15, 20, 15, NAKED)[0] == 16


def test_crossbow_bolt_goes_through_plate():
    plate, through = _hit("pierce", 30, 55, 25, PLATE_STACK)
    naked, _ = _hit("pierce", 30, 55, 25, NAKED)
    assert plate == 31 and naked == 31
    assert through.reached_flesh is True


def test_demon_claw_is_cushioned_not_stopped():
    plate, _ = _hit("crush", 40, 0, 120, PLATE_STACK)
    naked, _ = _hit("crush", 40, 0, 120, NAKED)
    assert plate == 37 and naked == 44
    assert plate >= int(0.70 * naked)


def test_gambeson_under_plate_cushions_a_crush_and_not_a_stopped_dart():
    both = (PLATE, GAMBESON, HIDE)
    dart_plate, plate_only = _hit("pierce", 4, 12, 2, PLATE_STACK)
    dart_both, with_gambeson = _hit("pierce", 4, 12, 2, both)
    assert dart_plate == dart_both == 0
    assert with_gambeson.stopped_at is PLATE
    assert with_gambeson.bruise == plate_only.bruise
    claw_plate = _hit("crush", 40, 0, 120, PLATE_STACK)[0]
    claw_both = _hit("crush", 40, 0, 120, both)[0]
    assert claw_both < claw_plate


def test_a_skin_pixel_is_the_hide_only():
    skin, result = _hit("pierce", 4, 12, 2, (HIDE,))
    assert skin == 4 and result.reached_flesh is True


def test_an_arrow_stops_on_demon_hide():
    landed_amount, result = _hit("pierce", 6, 30, 4, (DEMON,))
    assert landed_amount == 0 and result.stopped_at is DEMON


def test_unknown_delivery_fails():
    try:
        physical("mind", 1, 0, 0, NAKED)
    except ValueError as exc:
        assert "mind" in str(exc)
    else:
        raise AssertionError("expected ValueError")
