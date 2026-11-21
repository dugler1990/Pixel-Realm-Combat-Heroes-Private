"""One damage path: the resolver decides (gate, invulnerable window, price), Entity.take_damage
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

pygame.init()

import hit_resolve  # noqa: E402
from Entity import Entity  # noqa: E402
from Interaction import InteractionContext, InteractionResolver  # noqa: E402
from damage_data import attack  # noqa: E402


def _body(**fields):
    """A body that runs Entity's own gate, receiver and take_damage."""
    body = SimpleNamespace(**{"team_id": "enemy_1", "health": 100, "vulnerable": True, "hit_time": 0,
                              "takes_impulse": True, "hurt": [], **fields})
    body.can_receive_interaction = lambda ctx: Entity.can_receive_interaction(body, ctx)
    body.receive_interaction = lambda ctx: Entity.receive_interaction(body, ctx)
    body.take_damage = lambda ctx: Entity.take_damage(body, ctx)
    body.on_hurt = body.hurt.append
    return body


def _hit(target, **fields):
    fields.setdefault("source_team", "player")
    return InteractionContext(kind="damage", source_kind="player_attack", target=target, **fields)


def test_a_hit_in_the_invulnerable_window_is_spent_and_starts_nothing(monkeypatch):
    started = []
    monkeypatch.setattr(hit_resolve, "apply_element", lambda *a: started.append(a))
    body = _body(vulnerable=False)
    ctx = _hit(body, amount=10, attack_def=attack("sword"))
    assert InteractionResolver().apply(ctx) is True   # spent: the attack does not try again
    assert body.health == 100 and body.hurt == [] and started == []
    assert not hasattr(body, "last_attacker_team")


def test_damage_over_time_is_not_stopped_by_the_window():
    body = _body(vulnerable=False)
    assert InteractionResolver().apply(_hit(body, amount=3, over_time=True)) is True
    assert body.health == 97 and len(body.hurt) == 1


def test_a_hit_with_no_amount_and_no_attack_def_takes_the_attackers_damage():
    source = SimpleNamespace(get_full_weapon_damage=lambda: 25, get_full_magic_damage=lambda: 40)
    body = _body()
    InteractionResolver().apply(_hit(body, source=source, attack_type="weapon"))
    InteractionResolver().apply(_hit(body, source=source, attack_type="magic"))
    assert body.health == 100 - 25 - 40


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
    assert resolver.apply(_hit(body, amount=5, source_team="enemy_1")) is False
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
