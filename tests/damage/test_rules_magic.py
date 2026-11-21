"""Fire, cold and lightning, row for row from elemental.plan.md (damage chunk 7). No display."""
import json
import math
import sys
from pathlib import Path

import pytest

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from damage_data import CATEGORIES, DamageDataError, LayerDef, attack, body, load_attacks  # noqa: E402
from damage_rules import (  # noqa: E402
    CATCH, COOK, bolt_body, bolt_chain, cold_band, cold_wound, elemental, heat_wound, resist_of,
)

HIDE = body("barb").natural


def _layer(flammability=0, insulation=0, conductivity=0):
    return LayerDef("piece", flammability=flammability, insulation=insulation, conductivity=conductivity)


def _fire(power, layer, resist=None):
    return elemental(fire=power, layer=layer, resist=resist or {})


def _cold(power, constitution=10, wet=False, resist=None, full=True):
    return elemental(cold=power, layer=HIDE, resist=resist or {}, constitution=constitution,
                     wet=wet, full=full)


def _step_heat(H, dt=0.001):
    if H <= COOK:
        return 0.0
    total = 0.0
    t = 0.0
    k = 0.25
    while True:
        h = H * math.exp(-k * t)
        if h <= COOK:
            return total
        total += (h - COOK) * k * dt
        t += dt


def _step_cold(sticks, constitution, dt=0.001):
    if sticks <= 12:
        return 0.0
    rate = 0.02 * constitution
    total = 0.0
    t = 0.0
    while True:
        c = sticks * math.exp(-rate * t)
        if c <= 12:
            return total
        total += (c - 12) * dt
        t += dt


def test_ice_loads_as_cold_and_lightning_as_its_four_knobs():
    ice = attack("ice_ball")
    assert ice.cold == 10 and ice.magic == ()
    assert ice.magic_mask & (1 << CATEGORIES.ids["ice"])
    assert attack("ghost_chill").cold == 20
    bolt = attack("storm_bolt").lightning
    assert (bolt.damage, bolt.reach, bolt.arcs, bolt.spark) == (50, 180, 4, 12)
    assert attack("flame").magic == ((CATEGORIES.ids["fire"], 5),)
    assert "wet" in body("squid").starts and body("squid").resist["ice"] == 20
    assert body("ice_ghost").resist["fire"] == -30


def test_bare_lightning_does_not_jump_and_cold_wins(tmp_path):
    path = tmp_path / "attacks.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "attacks": {
            "zap": {"magic": {"lightning": 50}},
            "chill": {"cold": 4, "magic": {"ice": 10}},
        },
    }))
    rows = {row.name: row for row in load_attacks(path)}
    assert (rows["zap"].lightning.damage, rows["zap"].lightning.reach, rows["zap"].lightning.arcs) == (50, 0, 0)
    assert rows["chill"].cold == 4 and rows["chill"].magic == ()
    path.write_text(json.dumps({
        "schema_version": 1,
        "attacks": {"bad": {"magic": {"lightning": {"damage": 1, "jumps": 2}}}},
    }))
    with pytest.raises(DamageDataError, match="unknown field"):
        load_attacks(path)


def test_fire_table():
    plate = _fire(15, _layer(insulation=0.2))
    assert round(plate.wound) == 3 and plate.heat_shade == "hot" and plate.starts[0][0] == "hot_shell"
    assert plate.starts[0][2] == pytest.approx(3502, abs=2)
    hide = _fire(15, HIDE)
    assert round(hide.wound) == 5 and hide.heat_shade == "hot" and hide.starts[0][0] == "hot_shell"
    assert hide.starts[0][2] == pytest.approx(4394, abs=2)
    cloth = _fire(15, _layer(flammability=0.8, insulation=0.1))
    assert cloth.wound == 15 and cloth.heat_shade == "searing" and cloth.starts == (("burning", None, 6000),)
    assert _fire(15, body("demon").natural, body("demon").resist).wound == 0
    assert _fire(9, body("spirit").natural, body("spirit").resist).wound == 0
    assert CATCH == 0.5


def test_parent_resist_cuts_the_power_and_a_weakness_raises_it():
    assert resist_of({"fire": 0, "elemental": 10}, "fire") == 10
    caught = _fire(12, _layer(flammability=0.8), {"elemental": 10})
    assert caught.wound == 2
    ghost = _fire(15, _layer(), body("ice_ghost").resist)      # fire -30: a weakness
    assert resist_of(body("ice_ghost").resist, "fire") == -30
    assert ghost.wound == _fire(45, _layer()).wound


def _hit(name, card_name, worn=()):
    """Price `name` on a body of `card_name` wearing `worn` (item bases), through hit_resolve."""
    from types import SimpleNamespace

    import json as _json
    from defence_profile import build_profile, natural_profile
    from hit_resolve import resolve
    from damage_rules import landed

    card = body(card_name)
    bases = _json.loads((Path(__file__).resolve().parents[2] / "Graphics" / "Standard_Items"
                         / "item_bases.json").read_text(encoding="utf-8"))
    if worn == "plate":
        worn = [n for n, b in bases.items() if not n.startswith("_") and b.get("set") == "fullplate"]
    defence = build_profile(card, [(n, bases[n], None) for n in worn]) if worn else natural_profile(card)
    target = SimpleNamespace(body_def=card, defence=defence, stats={}, conditions={})
    ctx = SimpleNamespace(kind="damage", attack_def=attack(name), target=target, source=None,
                          scale=1.0, contact=None, toward=None)
    return landed(resolve(ctx, 0))


def test_holy_is_times_the_kind_and_goes_through_plate():
    assert _hit("sun_bolt", "demon") == 16                    # holy 8 x 2
    assert _hit("sun_bolt", "barb") == 4                      # living x 0.5
    assert _hit("sun_bolt", "barb", "plate") == 4               # plate does not stop it
    assert _hit("curse_bolt", "ice_ghost") == 0               # unholy does nothing to undead


def test_holy_on_a_blow_adds_to_what_gets_through():
    from damage_rules import sacred
    holy = CATEGORIES.ids["holy"]
    assert sacred(((holy, 20),), 0, 1.0, {}, "demon") == 40
    assert sacred(((holy, 20),), 0, 1.0, {"holy": -10}, "living") == 15   # weakness adds
    assert sacred(((holy, 20),), 0, 1.0, {}, "construct") == 0


def test_cold_table():
    hero = _cold(20)
    assert round(hero.wound) == 9 and hero.cold_shade == "severe"
    assert hero.starts[0][0] == "chilled" and hero.starts[0][1] == -3
    assert hero.starts[0][2] == pytest.approx(3466, abs=2)
    hardy = _cold(20, constitution=20)
    assert hardy.wound == 0 and hardy.starts == () and hardy.cold_shade is None
    wet = _cold(20, wet=True)
    assert round(wet.wound) == 29 and wet.cold_shade == "severe"
    assert wet.starts[0][2] == pytest.approx(5148, abs=2)
    assert _cold(20, resist=body("ice_ghost").resist).wound == 0


def test_constitution_20_sticks_half_and_the_slow_ends_sooner():
    soft = _cold(20, constitution=10)
    hardy = _cold(20, constitution=20)
    assert hardy.starts == ()
    assert soft.starts[0][2] > 0


def test_shade_boundaries():
    assert [cold_band(n) for n in (9, 10, 15, 20)] == [None, "mild", "medium", "severe"]


def test_a_simple_body_uses_the_shade_row_not_the_curve():
    simple = _cold(20, full=False)
    assert simple.wound == 8 and simple.cold_shade == "severe"
    assert simple.starts == (("chilled", -3, 6000),)
    assert simple.wound != round(cold_wound(20, 10))


def test_heat_and_cold_curves_match_a_1ms_step():
    assert abs(heat_wound(12) - _step_heat(12)) < 0.05
    assert abs(cold_wound(20, 10) - _step_cold(20, 10)) < 0.05
    assert abs(cold_wound(28, 10) - _step_cold(28, 10)) < 0.05


def test_storm_bolt_jumps_by_charge_and_stops():
    wound, passed, nxt = bolt_body(50, 0.9, False, 0, 50, 180)
    assert (wound, passed, nxt) == pytest.approx((95, 45, 162))
    wet, passed2, nxt2 = bolt_body(passed, 0, True, 0, 50, 180)
    assert (wet, passed2, nxt2) == pytest.approx((67.5, 18, 64.8))
    near = [(0, 0.9, False, 0), (100, 0.0, True, 0)]
    far = [(0, 0.9, False, 0), (200, 0.0, True, 0)]
    assert bolt_chain(50, 180, 4, 12, near, full=True) == pytest.approx([95, 67.5])
    assert bolt_chain(50, 180, 4, 12, far, full=True) == pytest.approx([95])
    dry, passed_dry, reach_dry = bolt_body(50, 0, False, 0, 50, 180)
    assert (dry, passed_dry, reach_dry) == (50, 0, 0)
    # The second body passes under spark, so the third, though close, is not hit.
    fading = [(0, 0.9, False, 0), (10, 0.2, False, 0), (10, 0.9, False, 0)]
    assert len(bolt_chain(50, 180, 4, 12, fading, full=True)) == 2
    # Simple jumps once even though charge remains and a third body is in reach.
    three = [(0, 0.9, False, 0), (100, 0.0, True, 0), (50, 0.0, True, 0)]
    assert len(bolt_chain(50, 180, 4, 12, three, full=True)) == 3
    assert len(bolt_chain(50, 180, 4, 12, three, full=False)) == 2
    bamboo, _, _ = bolt_body(50, 0, False, 30, 50, 180)
    assert bamboo == 20


def test_apply_fire_spit_on_loincloth_burns():
    from types import SimpleNamespace
    from Interaction import LANDED, InteractionContext, InteractionResolver
    from conditions import ConditionClock, condition
    from defence_profile import DefenceProfile, SLOTS
    cloth = _layer(flammability=0.8, insulation=0.1)
    profile = DefenceProfile(body("barb"), ((cloth, HIDE),) * len(SLOTS), 0.3, True)
    clock = ConditionClock()

    class Body:
        def __init__(self):
            self.body_def = body("barb")
            self.defence = profile
            self.team_id = "enemy_1"
            self.health = 100
            self.conditions = {}
            self.condition_gen = 0
            self.id = 7
            self.detail = "full"
            self.level = SimpleNamespace(condition_clock=clock)
            self.piece_layers = {}

        def can_receive_interaction(self, ctx):
            return True

        def receive_interaction(self, ctx):
            self.health -= ctx.amount

    class Source:
        stats = {}
        team_id = "player"

    target = Body()
    ctx = InteractionContext(
        kind="damage", source_kind="player_attack", source=Source(), source_team="player",
        target=target, attack_type="magic", attack_def=attack("fire_spit"),
    )
    assert InteractionResolver().apply(ctx) is LANDED
    assert target.health == 85
    assert condition("burning").id in target.conditions
    assert target.heat_shade == "searing" and target.heat_on_skin is False


def test_heat_patch_uses_insulation_and_not_fire_resistance():
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    from types import SimpleNamespace
    from conditions import ConditionClock, condition
    from defence_profile import DefenceProfile, SLOTS
    from Effect import HeatEffect
    plate = _layer(insulation=0.2)
    profile = DefenceProfile(body("barb"), ((plate, HIDE),) * len(SLOTS), 1.0, True)
    clock = ConditionClock()
    entity = SimpleNamespace(
        body_def=body("barb"), defence=profile, fire_resistance=100,
        conditions={}, condition_gen=0, id=3, piece_layers={},
        level=SimpleNamespace(condition_clock=clock),
    )
    hot = HeatEffect({"heat": 10})
    dealt = hot.get_environmental_damage(entity, 1.0)
    assert dealt[0] == pytest.approx(8)
    hot.remove(entity)
    assert condition("hot_shell").id in entity.conditions
    quiet = SimpleNamespace(
        body_def=body("barb"), defence=profile, fire_resistance=0,
        conditions={}, condition_gen=0, id=4, piece_layers={},
        level=SimpleNamespace(condition_clock=ConditionClock()),
    )
    HeatEffect({"heat": 5}).remove(quiet)
    assert quiet.conditions == {}
