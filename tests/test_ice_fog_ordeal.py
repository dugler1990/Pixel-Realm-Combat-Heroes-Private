"""Fog ordeal wrap, escape stub, sequence, and pads."""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ice_fog"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from ice_fog.config import load_ordeal_config
from ice_fog.ordeal import FogOrdeal


def _types(events):
    return [e["type"] for e in events]


def test_enter_sets_tangled_and_whispers():
    ordeal = FogOrdeal(load_ordeal_config(FIXTURES / "ordeal_wrap.json"))
    events = ordeal.update_position(200, 200, now_ms=0)
    assert ordeal.tangled
    assert "entered" in _types(events)
    assert any(e["type"] == "whisper" and e["line_id"] == "fog_enter" for e in events)


def test_outside_while_clear_does_nothing():
    ordeal = FogOrdeal(load_ordeal_config(FIXTURES / "ordeal_wrap.json"))
    events = ordeal.update_position(500, 500, now_ms=0)
    assert not ordeal.tangled
    assert events == []


def test_wrap_teleports_to_opposite_side():
    ordeal = FogOrdeal(load_ordeal_config(FIXTURES / "ordeal_wrap.json"))
    ordeal.update_position(200, 200, now_ms=0)
    events = ordeal.update_position(400, 200, now_ms=1000)
    assert "teleported" in _types(events)
    tele = next(e for e in events if e["type"] == "teleported")
    assert tele["to"][0] < 200
    assert ordeal.circle.is_inside(*tele["to"])
    assert ordeal.tangled


def test_wrap_cooldown_suppresses_second_teleport_event():
    ordeal = FogOrdeal(load_ordeal_config(FIXTURES / "ordeal_wrap.json"))
    ordeal.update_position(200, 200, now_ms=0)
    first = ordeal.update_position(400, 200, now_ms=1000)
    assert "teleported" in _types(first)
    second = ordeal.update_position(400, 200, now_ms=1100)
    assert "teleported" not in _types(second)
    # Still contained inside after cooldown snap.
    assert ordeal.circle.is_inside(*ordeal.position())


def test_complete_escape_allows_walk_out():
    ordeal = FogOrdeal(load_ordeal_config(FIXTURES / "ordeal_wrap.json"))
    ordeal.update_position(200, 200, now_ms=0)
    esc = ordeal.complete_escape()
    assert esc[0]["how"] == "task"
    assert not ordeal.tangled
    events = ordeal.update_position(500, 500, now_ms=5000)
    assert "teleported" not in _types(events)
    assert not ordeal.tangled


def test_sequence_escape_main_route():
    ordeal = FogOrdeal(load_ordeal_config(FIXTURES / "ordeal_sequence.json"))
    ordeal.update_position(200, 200, now_ms=0)
    # Exit north, west, south, west — sectors from outside points.
    steps = [
        (200, -50, 1000),   # N
        (-50, 200, 2000),   # W
        (200, 450, 3000),   # S
        (-50, 200, 4000),   # W
    ]
    escaped = False
    for x, y, t in steps:
        # After each teleport we sit inside; next outside push is a new wrap.
        events = ordeal.update_position(x, y, now_ms=t)
        if any(e["type"] == "escaped" for e in events):
            escaped = True
            route = next(e for e in events if e["type"] == "escaped")
            assert route["how"] == "sequence"
            assert route["route"] == "main"
            break
        # Apply suggested position for next step realism
        assert ordeal.circle.is_inside(*ordeal.position())
    assert escaped
    assert not ordeal.tangled


def test_wrong_sequence_resets_but_stays_tangled():
    ordeal = FogOrdeal(load_ordeal_config(FIXTURES / "ordeal_sequence.json"))
    ordeal.update_position(200, 200, now_ms=0)
    ordeal.update_position(200, -50, now_ms=1000)  # N — prefix of main and secret
    events = ordeal.update_position(400, 200, now_ms=2000)  # E — not next for main (W) or secret (N)
    assert ordeal.tangled
    assert "sequence_reset" in _types(events) or ordeal.path.steps == []


def test_secret_sequence_escape():
    ordeal = FogOrdeal(load_ordeal_config(FIXTURES / "ordeal_sequence.json"))
    ordeal.update_position(200, 200, now_ms=0)
    # N, N, E via wraps with cooldown gaps.
    for x, y, t in [
        (200, -50, 1000),
        (200, -50, 2000),
        (400, 200, 3000),
    ]:
        events = ordeal.update_position(x, y, now_ms=t)
        if any(e.get("route") == "secret" for e in events):
            assert not ordeal.tangled
            return
    pytest.fail("secret route did not complete via wraps")


def test_pad_order_escape():
    ordeal = FogOrdeal(load_ordeal_config(FIXTURES / "ordeal_pads.json"))
    ordeal.update_position(200, 200, now_ms=0)
    # Near-rim points for A (E), B (N), C (W)
    points = [
        (200 + 110, 200),       # A east
        (200, 200 - 110),       # B north
        (200 - 110, 200),       # C west
    ]
    escaped = False
    t = 0
    for x, y in points:
        t += 500
        events = ordeal.update_position(x, y, now_ms=t)
        if any(e["type"] == "escaped" and e["how"] == "pads" for e in events):
            escaped = True
            break
    assert escaped
    assert not ordeal.tangled


def test_wrong_pad_resets_progress():
    ordeal = FogOrdeal(load_ordeal_config(FIXTURES / "ordeal_pads.json"))
    ordeal.update_position(200, 200, now_ms=0)
    ordeal.update_position(200, 200 - 110, now_ms=500)  # B first — wrong
    assert ordeal.pads.progress == 0
    ordeal.update_position(200 + 110, 200, now_ms=1000)  # A — starts order
    assert ordeal.pads.progress == 1
