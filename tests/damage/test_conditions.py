"""The condition clock (damage chunk 6). No display."""
import json
import sys
from pathlib import Path

import pytest

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from conditions import (  # noqa: E402
    CONDITIONS,
    ConditionClock,
    condition,
    load_conditions,
    save_succeeds,
    speed_of,
)
from damage_data import DamageDataError  # noqa: E402


class Stub:
    def __init__(self, entity_id, speed=10):
        self.id = entity_id
        self.stats = {"speed": speed}
        self.conditions = {}
        self.condition_gen = 0


def _pair(tmp_path):
    """haste plus a second buff, so a cure can leave one behind."""
    path = tmp_path / "conditions.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "conditions": {
            "haste": {"kind": "buff", "stat": "speed", "amount": 4, "duration_ms": 8000, "stack": "refresh"},
            "guard": {"kind": "buff", "stat": "attack", "amount": 1, "duration_ms": 8000, "stack": "refresh"},
        },
    }), encoding="utf-8")
    defs = load_conditions(path)
    return ConditionClock(defs=defs), defs


def test_file_loads_with_ids_in_order():
    assert [d.id for d in CONDITIONS] == list(range(len(CONDITIONS)))
    haste = condition("haste")
    assert haste is CONDITIONS[haste.id]
    assert (haste.kind, haste.stat, haste.amount, haste.duration_ms, haste.stack) == (
        "buff", "speed", 4, 8000, "refresh",
    )


def test_unknown_field_names_the_row(tmp_path):
    path = tmp_path / "conditions.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "conditions": {
            "haste": {"kind": "buff", "stat": "speed", "amount": 4, "duration_ms": 8000,
                      "stack": "refresh", "colour": "red"},
        },
    }), encoding="utf-8")
    with pytest.raises(DamageDataError, match="haste"):
        load_conditions(path)


def test_unknown_kind_names_the_row(tmp_path):
    path = tmp_path / "conditions.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "conditions": {
            "haste": {"kind": "curse", "stat": "speed", "amount": 4, "duration_ms": 8000, "stack": "refresh"},
        },
    }), encoding="utf-8")
    with pytest.raises(DamageDataError, match="haste"):
        load_conditions(path)


def test_unknown_stack_names_the_row(tmp_path):
    path = tmp_path / "conditions.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "conditions": {
            "haste": {"kind": "buff", "stat": "speed", "amount": 4, "duration_ms": 8000, "stack": "add"},
        },
    }), encoding="utf-8")
    with pytest.raises(DamageDataError, match="haste"):
        load_conditions(path)


def test_heap_pops_only_what_is_due_and_equal_ends_follow_seq():
    clock = ConditionClock()
    a, b, c = Stub(1), Stub(2), Stub(3)
    bodies = {1: a, 2: b, 3: c}
    clock.start(a, "haste", 0, duration_ms=500)
    clock.start(b, "haste", 0, duration_ms=100)
    clock.start(c, "haste", 0, duration_ms=500)
    clock.tick(100, bodies)
    assert b.conditions == {}
    assert a.conditions and c.conditions
    clock.tick(499, bodies)
    assert a.conditions and c.conditions
    order = []
    import conditions as conditions_mod
    real = conditions_mod.heapq.heappop

    def spy(heap):
        row = real(heap)
        order.append(row[2])
        return row

    conditions_mod.heapq.heappop = spy
    try:
        clock.tick(500, bodies)
    finally:
        conditions_mod.heapq.heappop = real
    assert order == [a.id, c.id]
    assert a.conditions == {} and c.conditions == {}


def test_cure_drops_one_and_leaves_the_other(tmp_path):
    clock, defs = _pair(tmp_path)
    body = Stub(1)
    clock.start(body, "haste", 0, duration_ms=100)
    clock.start(body, "guard", 0, duration_ms=100)
    clock.cure(body, "haste")
    assert clock.bonus(body, "speed") == 0
    guard_id = next(d.id for d in defs if d.name == "guard")
    assert guard_id in body.conditions
    clock.tick(100, {1: body})
    assert guard_id not in body.conditions


def test_death_clears_and_a_missing_body_is_skipped():
    clock = ConditionClock()
    body = Stub(1)
    clock.start(body, "haste", 0, duration_ms=100)
    gen = body.condition_gen
    clock.on_death(body)
    assert body.condition_gen == gen + 1
    assert body.conditions == {}
    clock.tick(100, {1: body})
    assert body.conditions == {}

    other = Stub(2)
    clock.start(other, "haste", 0, duration_ms=50)
    clock.tick(50, {})
    assert other.conditions
    clock.tick(50, {})
    assert other.conditions


def test_save_succeeds_replays_from_the_seed():
    def rolls(seed):
        clock = ConditionClock(seed)
        return [save_succeeds(clock.rng, 0, 11) for _ in range(8)]

    assert rolls(7) == rolls(7)
    assert rolls(7) != rolls(8)


def test_haste_adds_four_then_ends_and_a_refresh_keeps_it():
    clock = ConditionClock()
    body = Stub(1, speed=10)
    clock.start(body, "haste", 0)
    assert speed_of(body) == 14
    clock.tick(8000, {1: body})
    assert speed_of(body) == 10

    clock.start(body, "haste", 0)
    clock.start(body, "haste", 1000)
    clock.tick(8000, {1: body})
    assert speed_of(body) == 14
    clock.tick(9000, {1: body})
    assert speed_of(body) == 10


def test_records_round_trip_keeps_the_bonus_and_the_end():
    clock = ConditionClock()
    first = Stub(1, speed=10)
    clock.start(first, "haste", 50)
    rows = clock.records(first)
    second = Stub(2, speed=10)
    clock.apply_records(second, rows, 50)
    assert speed_of(second) == speed_of(first) == 14
    assert clock.records(second) == rows
