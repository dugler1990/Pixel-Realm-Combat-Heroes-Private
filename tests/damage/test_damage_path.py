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
    assert not hasattr(body, "recent_attacker_team_id") and not hasattr(body, "retaliate_team_id")


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


def test_the_gate_refuses_own_team_no_health_left_and_shoves_on_a_fixed_body():
    body = _body()
    assert Entity.can_receive_interaction(body, _hit(body, amount=1, source_team="enemy_1")) is False
    body.health = 0
    assert Entity.can_receive_interaction(body, _hit(body, amount=1)) is False
    shove = InteractionContext(kind="impulse", source_kind="test", source_team="player", target=body)
    assert Entity.can_receive_interaction(body, shove) is True
    body.takes_impulse = False
    assert Entity.can_receive_interaction(body, shove) is False


def test_the_resolver_remembers_the_attacker_for_a_body_that_keeps_it():
    body = _body(recent_attacker_team_id=None, recent_attacker_until_ms=0)
    InteractionResolver().apply(_hit(body, amount=1))
    assert body.recent_attacker_team_id == "player" and body.recent_attacker_until_ms > 0
