"""The temperature store (temperature step 2): sources on a full body, settle through the resolver,
the wake queue, paint. Stub bodies; times are passed in."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()

import pytest  # noqa: E402

import temperature  # noqa: E402
from Entity import Entity  # noqa: E402
from Interaction import InteractionResolver  # noqa: E402
from conditions import ConditionClock, condition, has  # noqa: E402
from damage_data import LayerDef, body as body_card  # noqa: E402
from damage_rules import AIR_K, BODY_K, COLD_SCALE, HURT_AT  # noqa: E402
from defence_profile import DefenceProfile, natural_profile, region_slot  # noqa: E402

PLATE = LayerDef("plate_test", stopping_power=40, absorb=0.15, weight=12, insulation=0.2)


def _level(air=0.0):
    return SimpleNamespace(air=air, interaction_resolver=InteractionResolver(),
                           condition_clock=ConditionClock())


def _body(level, vitality=None, plate=False, card="barb"):
    card = body_card(card)
    defence = natural_profile(card)
    if plate:
        layers = list(defence.layers)
        layers[region_slot("chest")] = (PLATE, card.natural)
        defence = DefenceProfile(card, tuple(layers), 12.0, True)
    body = SimpleNamespace(id=id(object()), team_id="player", health=1e6, hit_time=0,
                           body_def=card, defence=defence, level=level, takes_impulse=True,
                           stats={} if vitality is None else {"vitality": vitality}, hurt=[])
    body.can_receive_interaction = lambda ctx: Entity.can_receive_interaction(body, ctx)
    body.receive_interaction = lambda ctx: Entity.receive_interaction(body, ctx)
    body.take_damage = lambda ctx: Entity.take_damage(body, ctx)
    body.on_hurt = body.hurt.append
    body.is_dead = False
    body.die = lambda: setattr(body, "is_dead", True)
    temperature.join(body, level, 0)
    return body


def _run(level, until_ms):
    """The level's wake queue, as Level4's frame loop drives it."""
    while level.warmth_wakes and level.warmth_wakes[0][0] <= until_ms:
        temperature.tick(level, level.warmth_wakes[0][0])


def test_at_rest_in_mild_air_nothing_moves_and_nothing_wakes():
    level = _level()
    body = _body(level)
    assert temperature.skin(body, 60_000) == 0.0
    assert not getattr(level, "warmth_wakes", None)


def test_naked_in_the_ice_settles_at_the_weighted_pull_and_wounds_through_the_resolver():
    level = _level()
    body = _body(level)
    temperature.set_air(level, -60.0, 0, [body])
    steady = AIR_K * -60.0 / (AIR_K + BODY_K)
    assert temperature.skin(body, 3_600_000) == pytest.approx(steady)
    curve = body.warmth.curve   # from 0 ms; every later solve continues this same curve
    _run(level, 600_000)
    temperature.settle(body, 600_000)
    lost = 1e6 - body.health
    expected = COLD_SCALE * curve.area_past(0, -HURT_AT, 0.0, 600.0, above=False)
    assert lost == pytest.approx(expected, abs=1.0)   # paid in whole points
    assert {ctx.source_kind for ctx in body.hurt} == {"temperature"}


def test_vitality_is_a_stronger_heater():
    level = _level()
    weak, strong = _body(level, vitality=20), _body(level, vitality=60)
    temperature.set_air(level, -60.0, 0, [weak, strong])
    assert temperature.skin(strong, 3_600_000) > temperature.skin(weak, 3_600_000)


def test_plate_keeps_the_skin_warmer_in_the_ice():
    level = _level()
    naked, plated = _body(level), _body(level, plate=True)
    temperature.set_air(level, -60.0, 0, [naked, plated])
    assert len(plated.warmth.curve.steady) == 2
    assert temperature.skin(plated, 3_600_000) > temperature.skin(naked, 3_600_000)


def test_sources_pull_as_a_weighted_average_and_removing_one_re_aims():
    level = _level()
    body = _body(level)
    ghost_a, ghost_b = SimpleNamespace(), SimpleNamespace()
    temperature.add_source(body, ("hold", 1), -10.0, 0.2, 0, placed_by=ghost_a)
    temperature.add_source(body, ("hold", 2), -10.0, 0.2, 0, placed_by=ghost_b)
    k = AIR_K + BODY_K + 0.4
    assert temperature.skin(body, 3_600_000) == pytest.approx(0.4 * -10.0 / k)
    temperature.remove_source(body, ("hold", 1), 1000, placed_by=ghost_a)
    k = AIR_K + BODY_K + 0.2
    assert temperature.skin(body, 3_600_000) == pytest.approx(0.2 * -10.0 / k)


def test_a_dead_holder_lets_go():
    level = _level()
    body = _body(level)
    ghost = SimpleNamespace()
    temperature.add_source(body, ("hold", 7), -10.0, 0.2, 0, placed_by=ghost)
    temperature.forget(ghost, 2000)
    assert ("hold", 7) not in body.warmth.sources
    assert temperature.skin(body, 3_600_000) == pytest.approx(0.0)


def test_ice_resist_cuts_the_cold_air():
    level = _level()
    body = _body(level, card="ice_ghost")   # ice resist 100
    temperature.set_air(level, -60.0, 0, [body])
    assert temperature.skin(body, 3_600_000) == pytest.approx(0.0)


def test_a_bump_across_zero_is_a_shock_and_a_small_one_is_not():
    level = _level()
    body = _body(level)
    assert temperature.bump(body, temperature.SKIN, 3.0, 0) == 0.0
    temperature.bump(body, temperature.SKIN, -13.0, 10)   # now about -10
    assert temperature.bump(body, temperature.SKIN, 25.0, 20) > 0.0


def test_an_invulnerable_body_spends_the_tick():
    level = _level()
    body = _body(level)
    level.condition_clock.start(body, "invulnerable", 0, duration_ms=10 ** 9)
    temperature.set_air(level, -60.0, 0, [body])
    _run(level, 300_000)
    assert body.health == 1e6


def test_the_chill_shows_while_the_skin_is_blue_and_clears_after():
    level = _level()
    body = _body(level)
    ghost = SimpleNamespace()
    temperature.add_source(body, ("hold", 3), -40.0, 0.5, 0, placed_by=ghost)
    _run(level, 30_000)
    temperature.settle(body, 30_000)
    assert body.cold_shade is not None and has(body, "chilled")
    temperature.forget(ghost, 30_000)
    _run(level, 600_000)
    assert body.cold_shade is None and not has(body, "chilled")


def test_putting_on_plate_keeps_the_skin_and_adds_the_piece():
    level = _level()
    body = _body(level)
    temperature.set_air(level, -60.0, 0, [body])
    before = temperature.skin(body, 20_000)
    layers = list(body.defence.layers)
    layers[region_slot("chest")] = (PLATE, body.body_def.natural)
    body.defence = DefenceProfile(body.body_def, tuple(layers), 12.0, True)
    temperature.refresh(body, 20_000)
    assert len(body.warmth.curve.steady) == 2
    assert temperature.skin(body, 20_000) == pytest.approx(before)
    assert temperature.outer(body, 20_000) == pytest.approx(before)
