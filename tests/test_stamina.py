"""Stamina pool: cap from vitality, pay, overdraw, recovery delay."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from stamina import (  # noqa: E402
    HEALTH_PER_UNPAID,
    RECOVER_DELAY_MS,
    max_stamina,
    pay,
    recover,
    recover_per_tick,
)


def test_cap_follows_vitality_with_a_floor():
    assert max_stamina({"vitality": 10}) == 80
    assert max_stamina({"vitality": 20}) == 160
    assert max_stamina({"vitality": 0}) == 40
    assert max_stamina(None) == 40


def test_pay_spends_the_pool_and_holds_recovery():
    entity = SimpleNamespace(stamina=80, health=200)
    result = pay(entity, 20, now_ms=1000)
    assert result == {"paid": 20.0, "shortfall": 0.0, "health_lost": 0.0}
    assert entity.stamina == 60
    assert entity.health == 200
    assert entity._stamina_recover_at == 1000 + RECOVER_DELAY_MS



class _Resolver:
    """Takes the health the way the real resolver would, without the game."""

    def apply(self, ctx):
        ctx.target.health -= ctx.amount


def test_shortfall_is_health_and_the_pool_stops_at_zero():
    entity = SimpleNamespace(stamina=5, health=100, level=SimpleNamespace(interaction_resolver=_Resolver()))
    result = pay(entity, 20, now_ms=0)
    assert result["paid"] == 5
    assert result["shortfall"] == 15
    assert result["health_lost"] == 15 * HEALTH_PER_UNPAID
    assert entity.stamina == 0
    assert entity.health == 100 - 15 * HEALTH_PER_UNPAID


def test_zero_cost_does_not_start_the_delay():
    entity = SimpleNamespace(stamina=10, health=50)
    pay(entity, 0, now_ms=500)
    assert entity.stamina == 10
    assert not hasattr(entity, "_stamina_recover_at")


def test_recover_waits_out_the_delay_then_a_dash():
    entity = SimpleNamespace(stamina=0, health=100, is_dead=False, _dash_runtime=None, stats=None)
    stats = {"vitality": 10}
    pay(entity, 20, now_ms=0)
    recover(entity, stats, now_ms=RECOVER_DELAY_MS - 1)
    assert entity.stamina == 0

    entity._dash_runtime = {"direction": "right"}
    recover(entity, stats, now_ms=RECOVER_DELAY_MS + 50)
    assert entity.stamina == 0

    entity._dash_runtime = None
    recover(entity, stats, now_ms=RECOVER_DELAY_MS)
    assert entity.stamina == recover_per_tick(stats)


def test_recover_stops_at_the_cap():
    stats = {"vitality": 10}
    entity = SimpleNamespace(stamina=max_stamina(stats) - 0.01, health=100, is_dead=False, _dash_runtime=None)
    recover(entity, stats, now_ms=0)
    assert entity.stamina == max_stamina(stats)
