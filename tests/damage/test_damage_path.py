"""One damage path: the resolver decides (team rule, gate, invulnerable, price), Entity.take_damage
applies, on_hurt reacts."""
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
import pytest  # noqa: E402

pygame.init()

import hit_resolve  # noqa: E402
from Entity import Entity  # noqa: E402
from Interaction import LANDED, REFUSED, SPENT, InteractionContext, InteractionResolver  # noqa: E402
from conditions import ConditionClock  # noqa: E402
from damage_data import attack  # noqa: E402


def _body(**fields):
    """A body that runs Entity's own gate, receiver and take_damage."""
    body = SimpleNamespace(**{"team_id": "enemy_1", "health": 100, "hit_time": 0,
                              "takes_impulse": True, "hurt": [], **fields})
    body.can_receive_interaction = lambda ctx: Entity.can_receive_interaction(body, ctx)
    body.receive_interaction = lambda ctx: Entity.receive_interaction(body, ctx)
    body.take_damage = lambda ctx: Entity.take_damage(body, ctx)
    body.on_hurt = body.hurt.append
    return body


def _hit(target, **fields):
    fields.setdefault("source_team", "player")
    return InteractionContext(kind="damage", source_kind="player_attack", target=target, **fields)


def _invulnerable(body, now=0):
    body.id = "b"
    ConditionClock().start(body, "invulnerable", now)
    return body


def test_an_invulnerable_body_spends_the_hit_and_starts_nothing(monkeypatch):
    started = []
    monkeypatch.setattr(hit_resolve, "apply_element", lambda *a: started.append(a))
    body = _invulnerable(_body())
    ctx = _hit(body, attack_def=attack("sword"))
    assert InteractionResolver().apply(ctx) is SPENT   # the attack does not try again
    assert body.health == 100 and body.hurt == [] and started == []
    assert not hasattr(body, "last_attacker_team")


def test_invulnerable_blocks_heat_too():
    body = _invulnerable(_body())
    heat = InteractionContext(kind="damage", source_kind="environment", source_team="environment",
                              target=body, amount=3, attack_type="heat")
    assert InteractionResolver().apply(heat) is SPENT
    assert body.health == 100


def test_no_grace_by_default_a_second_hit_lands_at_once():
    body = _body()
    resolver = InteractionResolver()
    assert resolver.apply(_hit(body, amount=5)) is LANDED
    assert resolver.apply(_hit(body, amount=5)) is LANDED
    assert body.health == 90


def test_a_def_on_a_body_with_no_card_is_its_damage_plus_the_attackers_stat():
    """The same formula for player and monster: the def's number, plus the stat it scales with."""
    source = SimpleNamespace(stats={"attack": 10, "magic": 40})
    body = _body()
    resolver = InteractionResolver()
    resolver.apply(_hit(body, source=source, attack_def=attack("sword")))       # 15 + 10
    assert body.health == 75
    resolver.apply(_hit(body, source=source, attack_def=attack("flame")))       # fire 5 + 40
    assert body.health == 30
    resolver.apply(_hit(body, source=SimpleNamespace(stats={}), attack_def=attack("spear_thrust"),
                        scale=0.5))                                              # 6 * 0.5
    assert body.health == 27


def test_holy_alone_is_its_power_even_on_a_carded_body():
    from damage_data import body as body_card
    from defence_profile import natural_profile
    card = body_card("warrior")
    body = _body(body_def=card, defence=natural_profile(card))
    InteractionResolver().apply(_hit(body, source=None, attack_def=attack("sun_bolt")))
    assert body.health == 100 - 8


@pytest.mark.parametrize("fields", [{}, {"amount": 5, "attack_def": attack("sword")}],
                         ids=["neither", "both"])
def test_a_hit_needs_a_def_or_an_amount_not_both(fields):
    with pytest.raises(ValueError):
        InteractionResolver().apply(_hit(_body(), **fields))


def test_take_damage_subtracts_stamps_and_reacts_and_zero_does_nothing():
    body = _body()
    Entity.take_damage(body, _hit(body, amount=0))
    assert body.health == 100 and body.hit_time == 0 and body.hurt == []
    Entity.take_damage(body, _hit(body, amount=7))
    assert body.health == 93 and body.hit_time >= 0 and len(body.hurt) == 1


def test_the_gate_refuses_no_health_left_and_shoves_on_a_fixed_body():
    """The body's gate does not rule on teams for damage: that is the resolver's one team rule."""
    body = _body()
    assert Entity.can_receive_interaction(body, _hit(body, amount=1, source_team="enemy_1")) is True
    body.health = 0
    assert Entity.can_receive_interaction(body, _hit(body, amount=1)) is False
    shove = InteractionContext(kind="impulse", source_kind="test", source_team="player", target=body)
    assert Entity.can_receive_interaction(body, shove) is True
    body.takes_impulse = False
    assert Entity.can_receive_interaction(body, shove) is False


def test_the_resolver_remembers_the_attacker_on_any_body():
    body = _body(team_id="neutral_passive")
    InteractionResolver().apply(_hit(body, amount=1, source_team="enemy_1"))
    assert body.last_attacker_team == "enemy_1" and body.last_attacker_until_ms > 0


def test_a_passive_faction_may_fight_back_only_while_the_memory_lasts():
    """Permission expires: before, should_aggro checked `until > 0`, so it never did."""
    resolver = InteractionResolver()
    body = SimpleNamespace(team_id="neutral_passive")
    attacker = SimpleNamespace(team_id="enemy_1")
    resolver.faction_policy.remember_attacker(body, "enemy_1", 1000)
    assert resolver.can_aggro(body, attacker, 1001) is True
    assert resolver.can_aggro(body, attacker, body.last_attacker_until_ms) is False


def test_the_one_team_rule_refuses_own_team_in_apply_and_in_strike():
    body = _body()
    resolver = InteractionResolver()
    assert resolver.apply(_hit(body, amount=5, source_team="enemy_1")) is REFUSED
    assert resolver.strike([body], kind="damage", source_kind="t", source_team="enemy_1", amount=5) == []
    assert body.health == 100
    assert resolver.strike([body], kind="damage", source_kind="t", source_team="player", amount=5) == [body]
    assert body.health == 95


def _mortal(**fields):
    """A body that also dies Entity's way; `deaths` counts its on_death calls."""
    body = _body(is_dead=False, deaths=[], **fields)
    body.die = lambda: Entity.die(body)
    body.on_death = lambda: body.deaths.append(1)
    return body


def test_a_killing_hit_dies_once_and_later_hits_do_not_die_again():
    body = _mortal(health=10)
    resolver = InteractionResolver()
    resolver.apply(_hit(body, amount=15))
    assert body.is_dead and body.deaths == [1]
    Entity.take_damage(body, _hit(body, amount=5))   # past the gate, still only one death
    assert body.deaths == [1]


def test_a_strike_that_kills_its_first_target_still_hits_the_rest():
    first, second = _mortal(health=5), _mortal(health=50)
    landed = InteractionResolver().strike([first, second], kind="damage", source_kind="t",
                                          source_team="player", amount=10)
    assert landed == [first, second]
    assert first.is_dead and first.deaths == [1]
    assert second.health == 40 and not second.is_dead
