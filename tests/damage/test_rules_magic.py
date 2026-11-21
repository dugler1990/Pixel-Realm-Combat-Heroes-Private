"""Fire, cold and lightning, row for row from elemental.plan.md (damage chunk 7). No display."""
import json
import math
import sys
from pathlib import Path

import pytest

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from damage_data import (  # noqa: E402
    CATEGORIES, BodyDef, DamageDataError, LayerDef, attack, body, load_attacks,
)
from damage_rules import (  # noqa: E402
    AIR_K, CATCH, COLD_K, COOK, HEAT_K, HURT_AT, Warmth, air_on_skin, bolt_body, bolt_chain,
    cold_band, cold_wound, elemental, heat_wound, resist_of, shock_wound, wake_ms, warmth_at,
    warmth_shade, wound_between,
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


def test_parent_resist_cuts_the_power_and_a_stored_weakness_does_not_raise_it():
    assert resist_of({"fire": 0, "elemental": 10}, "fire") == 10
    caught = _fire(12, _layer(flammability=0.8), {"elemental": 10})
    assert caught.wound == 2
    ghost = _fire(15, _layer(), body("ice_ghost").resist)
    bare = _fire(15, _layer())
    assert round(ghost.wound) == round(bare.wound) == 5
    assert ghost.wound < _fire(45, _layer()).wound


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


def test_apply_fire_spit_on_loincloth_burns_and_does_not_ask_magic():
    from types import SimpleNamespace
    from Interaction import InteractionContext, InteractionResolver
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
        stats = {"magic": 99}
        team_id = "player"

        def get_full_magic_damage(self):
            raise AssertionError("get_full_magic_damage")

    target = Body()
    ctx = InteractionContext(
        kind="damage", source_kind="player_attack", source=Source(), source_team="player",
        target=target, attack_type="magic", attack_def=attack("fire_spit"),
    )
    assert InteractionResolver().apply(ctx) is True
    assert target.health == 85
    assert condition("burning").id in target.conditions
    assert target.heat_shade == "searing" and target.heat_on_skin is False


def test_air_on_skin_is_resist_then_clothes_then_vitality():
    naked = dict(resist={}, insulation=0.0, vitality=20)
    assert air_on_skin(0, **naked) == 0
    assert air_on_skin(-30, **naked) == pytest.approx(-30)
    assert air_on_skin(-30, resist={}, insulation=0.0, vitality=60) == pytest.approx(-10)
    assert air_on_skin(-30, resist={"ice": 30}, insulation=0.0, vitality=20) == pytest.approx(0)
    assert air_on_skin(-30, resist={}, insulation=0.2, vitality=20) == pytest.approx(-24)
    assert air_on_skin(20, **naked) == pytest.approx(20)
    assert air_on_skin(20, resist={"fire": 30}, insulation=0.0, vitality=20) == pytest.approx(0)
    assert air_on_skin(20, resist={}, insulation=0.2, vitality=20) == pytest.approx(16)
    # A missing vitality is the ordinary barb, not a divide by zero.
    assert air_on_skin(-30, {}, 0.0, None) == pytest.approx(-30)


def test_a_spike_toward_comfort_pays_the_cook_once():
    # Heat 12 falling to 0 at HEAT_K is the chunk 7 cook, and the fall is not paid again.
    sample = Warmth(12, 0, 0.0, HEAT_K, quiet_ms=int(round(math.log(12 / COOK) / HEAT_K * 1000)))
    assert warmth_at(sample, 0) == pytest.approx(12)
    assert warmth_shade(12) == "hot"
    assert warmth_shade(4) == "faint"
    assert warmth_shade(1) is None
    assert wound_between(sample, 0, 10_000) == pytest.approx(0)
    paid = heat_wound(12)
    assert paid == pytest.approx(heat_wound(12))
    # Past the quiet instant the shell is under COOK.
    assert warmth_at(sample, sample.quiet_ms) == pytest.approx(COOK, abs=0.05)
    assert shock_wound(-10, 5) == pytest.approx(heat_wound(15))
    assert shock_wound(-15, 0) == pytest.approx(heat_wound(15))
    assert shock_wound(0, 12) == 0
    assert shock_wound(-4, -1) == 0
    # The solved fall, with no quiet window, is the chunk 7 cook. A handful of multiplies.
    assert wound_between(Warmth(12, 0, 0.0, HEAT_K), 0, 100_000) == pytest.approx(heat_wound(12), abs=0.05)
    assert wound_between(Warmth(-20, 0, 0.0, COLD_K * 10), 0, 100_000) == pytest.approx(
        cold_wound(20, 10), abs=0.05)
    # The ice field's next wake is the hurt line, not the next frame.
    assert wake_ms(Warmth(0.0, 0, -30.0, AIR_K), 0) > 10_000


def test_held_past_the_line_wounds_and_a_safe_settle_does_not():
    # Ice field, naked, vitality 20: target -30. A long stay wounds.
    ice = Warmth(0.0, 0, -30.0, AIR_K, quiet_ms=0)
    long = 20_000_000
    assert warmth_at(ice, long) == pytest.approx(-30, abs=0.01)
    assert wound_between(ice, 0, long) > 100
    # Vitality 60 settles at -10, under the hurt line.
    mild = Warmth(0.0, 0, -10.0, AIR_K, quiet_ms=0)
    assert warmth_at(mild, long) == pytest.approx(-10, abs=0.01)
    assert wound_between(mild, 0, long) == pytest.approx(0)
    # Plate reaches -12 later than naked.
    plate = Warmth(0.0, 0, -24.0, AIR_K, quiet_ms=0)

    def _hit(sample, line):
        lo, hi = 0, long
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if warmth_at(sample, mid) <= line:
                hi = mid
            else:
                lo = mid
        return hi

    assert _hit(plate, -12) > _hit(ice, -12)
    desert = Warmth(0.0, 0, 20.0, AIR_K, quiet_ms=0)
    still = wound_between(desert, 0, 200_000)
    hotter = wound_between(Warmth(9.0, 0, 16.0, AIR_K, quiet_ms=0), 0, 200_000)
    assert hotter > still > 0


def _body(air=0.0, vitality=None, resist=None, insulation=0.0, health=100.0):
    """A full body with no pygame. Insulation 0 wears nothing."""
    from types import SimpleNamespace
    from conditions import ConditionClock
    from defence_profile import DefenceProfile, SLOTS

    card = body("barb")
    if resist:
        card = BodyDef(card.id, card.name, card.kind, card.natural, dict(resist), card.starts)
    defence = None
    if insulation:
        plate = _layer(insulation=insulation)
        defence = DefenceProfile(card, ((plate, card.natural),) * len(SLOTS), 1.0, True)
    clock = ConditionClock()
    return SimpleNamespace(
        body_def=card, defence=defence, detail="full", health=health, stats={} if vitality is None else {"vitality": vitality},
        conditions={}, condition_gen=0, id=id(card) ^ int(air * 10) ^ int((vitality or 0) * 10),
        piece_layers={}, level=SimpleNamespace(air=air, condition_clock=clock),
        cold_shade=None, heat_shade=None, heat_on_skin=False, heat_piece=None,
        team_id="enemy_1",
    )


def _let_it_take(body):
    """The resolver will not touch a body that cannot receive."""
    body.can_receive_interaction = lambda ctx: True

    def _take(ctx, who=body):
        who.health -= ctx.amount

    body.receive_interaction = _take


def test_flame_on_plate_is_faint_and_delays_the_ghost():
    from hit_resolve import set_ghost_hold, temper
    plate = _body(insulation=0.2)
    paid = temper(plate, 0, blow_heat=4.0)
    assert paid == 0
    assert warmth_shade(plate._piece.value) == "faint"
    assert plate.cold_shade is None
    set_ghost_hold(plate, True, 0)
    # The plate is still warmer than the hold, so the skin is not blue yet.
    assert plate._skin.value > -10
    assert plate.cold_shade is None
    temper(plate, 500)
    assert plate.cold_shade is None
    temper(plate, 8_000)
    assert plate._skin.value == pytest.approx(-10)
    assert plate.cold_shade == "mild"


def test_a_spit_pays_its_cook_once_then_fades():
    from hit_resolve import temper
    plate = _body(insulation=0.2)
    paid = temper(plate, 0, blow_heat=12.0)
    assert paid == pytest.approx(heat_wound(12))
    assert warmth_shade(plate._piece.value) == "hot"
    # Naked would be under COOK by now. The plate still holds it, and the cook is not paid again.
    assert warmth_at(plate._piece, 3_600) > COOK
    later = temper(plate, 8_000)
    assert later == pytest.approx(0, abs=0.05)
    assert plate._piece.value < COOK


def test_a_spit_onto_cold_skin_pays_cook_and_shock_and_finishes_hot():
    from hit_resolve import temper
    bare = _body()
    temper(bare, 0)
    bare._skin.value = -10.0
    bare._skin.at_ms = 0
    paid = temper(bare, 0, blow_heat=15.0, on_skin=True)
    assert paid == pytest.approx(heat_wound(15) + heat_wound(15))
    assert bare._skin.value == pytest.approx(5)
    assert bare.cold_shade is None


def test_equal_hot_and_cold_finish_at_comfort_and_the_shock_is_paid():
    from hit_resolve import temper
    bare = _body()
    temper(bare, 0, blow_heat=-15.0, on_skin=True)
    before = bare.health
    paid = temper(bare, 0, blow_heat=15.0, on_skin=True)
    assert bare._skin.value == pytest.approx(0)
    assert paid == pytest.approx(heat_wound(15) + shock_wound(-15, 0))
    assert before - bare.health == pytest.approx(paid)


def test_ghost_hold_settles_mild_and_does_not_wound():
    from conditions import condition
    from hit_resolve import set_ghost_hold
    bare = _body(health=100)
    paid = set_ghost_hold(bare, True, 0)
    assert paid == 0
    assert bare._skin.value == pytest.approx(-10)
    assert bare.cold_shade == "mild"
    assert condition("chilled").id in bare.conditions
    assert bare.health == 100
    # Still there a long time: still mild, still no wound.
    from hit_resolve import temper
    assert temper(bare, 60_000) == pytest.approx(0)
    assert bare._skin.value == pytest.approx(-10)


def test_ice_and_desert_settle_where_the_table_says():
    from hit_resolve import exert, temper
    ice = _body(air=-30)
    temper(ice, 0)
    temper(ice, 20_000_000)
    assert ice._skin.value == pytest.approx(-30, abs=0.05)
    assert ice.health < 0  # an ordinary body does not survive the stay

    hardy = _body(air=-30, vitality=60)
    temper(hardy, 0)
    assert temper(hardy, 20_000_000) == pytest.approx(0)
    assert hardy._skin.value == pytest.approx(-10, abs=0.05)

    immune = _body(air=-30, resist={"ice": 30})
    temper(immune, 0)
    assert temper(immune, 20_000_000) == pytest.approx(0)
    assert immune._skin.value == pytest.approx(0, abs=0.05)

    plated = _body(air=-30, insulation=0.2)
    temper(plated, 0)
    bare = _body(air=-30)
    temper(bare, 0)
    assert wake_ms(plated._skin, 0) > wake_ms(bare._skin, 0)
    temper(plated, 20_000_000)
    assert plated._skin.value == pytest.approx(-24, abs=0.05)
    assert plated.health < 0

    sun = _body(air=20)
    temper(sun, 0)
    temper(sun, 20_000_000)
    assert sun._skin.value == pytest.approx(20, abs=0.05)
    assert sun.health < 0

    shaded = _body(air=20, resist={"fire": 30})
    temper(shaded, 0)
    assert temper(shaded, 20_000_000) == pytest.approx(0)
    assert shaded._skin.value == pytest.approx(0, abs=0.05)

    clothed = _body(air=20, insulation=0.2)
    temper(clothed, 0)
    temper(clothed, 20_000_000)
    assert clothed._skin.value == pytest.approx(16, abs=0.05)
    assert clothed.health < 0


def test_three_slides_in_the_desert_wound_more_than_standing_still():
    from hit_resolve import exert, temper

    def _stay(slides):
        body = _body(air=20, insulation=0.2, health=10_000)
        temper(body, 0)
        if slides:
            exert(body, 20, 0)
            exert(body, 20, 1_000)
            exert(body, 20, 2_000)
        temper(body, 200_000)
        return 10_000 - body.health

    assert _stay(True) > _stay(False) > 0


def test_one_slide_pulls_a_mild_cold_toward_comfort():
    from hit_resolve import exert, temper
    cool = _body(air=-4)
    temper(cool, 0)
    cool._skin.value = -4.0
    cool._skin.at_ms = 0
    exert(cool, 20, 0)
    assert cool._skin.value == pytest.approx(-1)
    assert abs(cool._skin.value) < 4


def test_caught_cloth_burns_and_a_ghost_does_not_put_it_out():
    from conditions import condition
    from hit_resolve import set_ghost_hold
    from Interaction import InteractionContext, InteractionResolver
    cloth = _layer(flammability=0.8, insulation=0.1)
    from defence_profile import DefenceProfile, SLOTS
    wearer = _body()
    wearer.defence = DefenceProfile(wearer.body_def, ((cloth, HIDE),) * len(SLOTS), 0.3, True)
    wearer.health = 100
    _let_it_take(wearer)
    from types import SimpleNamespace
    ctx = InteractionContext(
        kind="damage", source_kind="player_attack", source=SimpleNamespace(stats={}), source_team="player",
        target=wearer, attack_type="magic", attack_def=attack("fire_spit"),
    )
    assert InteractionResolver().apply(ctx) is True
    assert wearer.health == 85
    assert condition("burning").id in wearer.conditions
    set_ghost_hold(wearer, True, 0)
    assert condition("burning").id in wearer.conditions
    assert wearer.heat_shade == "searing"
    assert wearer.health == 85


def test_a_plate_spit_is_not_cooked_twice():
    from defence_profile import DefenceProfile, SLOTS
    from Interaction import InteractionContext, InteractionResolver
    from types import SimpleNamespace
    plate = _layer(insulation=0.2)
    wearer = _body(health=100)
    wearer.defence = DefenceProfile(wearer.body_def, ((plate, HIDE),) * len(SLOTS), 1.0, True)
    _let_it_take(wearer)
    ctx = InteractionContext(
        kind="damage", source_kind="player_attack", source=SimpleNamespace(stats={}), source_team="player",
        target=wearer, attack_type="magic", attack_def=attack("fire_spit"),
    )
    assert InteractionResolver().apply(ctx) is True
    assert wearer.health == pytest.approx(100 - round(heat_wound(12)))


def test_lava_on_a_full_body_feeds_the_store_and_a_simple_body_keeps_the_tick():
    from Effect import HeatEffect
    from conditions import condition
    full = _body(health=100)
    hot = HeatEffect({"heat": 100})
    assert hot.get_environmental_damage(full, 1.0) is None
    assert full._lava_heat == 100
    assert full.health == 100  # nothing per frame; the clock owes the stay
    hot.remove(full)
    assert full._lava_heat is None
    assert condition("hot_shell").id not in full.conditions


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
