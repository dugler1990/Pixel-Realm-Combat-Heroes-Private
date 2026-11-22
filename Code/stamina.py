"""Stamina pool. The bar and a later heartbeat both read this number.

Full is rested. Empty is as hard as the body can go before it starts paying in
health. An action names a cost. What is left is spent; the unpaid part comes
off health, and the action still happens. A heartbeat would draw the same
pool as exertion (empty bar = heart pinned at its ceiling).

The size of the pool and how fast it comes back follow vitality. There is no
constitution attribute yet; vitality is the body stat.
"""

from __future__ import annotations

import temperature
from Interaction import InteractionContext

# One unpaid stamina point. A slide costs 20, so a dash on an empty bar is 40 health.
HEALTH_PER_UNPAID = 2.0
# No recovery during a dash, and none until this long after the last spend,
# so a chain of dashes does not refill between presses.
RECOVER_DELAY_MS = 450


def max_stamina(stats) -> float:
    """How far the body can go before further effort costs health."""
    vitality = 0.0
    if isinstance(stats, dict):
        vitality = float(stats.get("vitality", 0) or 0)
    # Floor keeps two slides (cost 20) even with no vitality.
    return max(40.0, vitality * 8.0)


def recover_per_tick(stats) -> float:
    """Added once per player update while resting. Same shape as energy regen."""
    vitality = 0.0
    if isinstance(stats, dict):
        vitality = float(stats.get("vitality", 0) or 0)
    return 0.04 * vitality


def pay(entity, cost, now_ms) -> dict:
    """Spend `cost` stamina. Shortfall is health. The caller still does the action.

    Returns paid, shortfall, and health_lost. A cost of 0 changes nothing.
    """
    cost = float(cost or 0)
    if cost <= 0:
        return {"paid": 0.0, "shortfall": 0.0, "health_lost": 0.0}

    current = float(getattr(entity, "stamina", 0) or 0)
    if current < 0:
        current = 0.0
    paid = min(current, cost)
    shortfall = cost - paid
    entity.stamina = current - paid

    # Every point spent is heat, the unpaid part too (temperature: stamina is heat).
    temperature.exert(entity, cost, now_ms)

    health_lost = 0.0
    if shortfall > 0:
        health_lost = int(round(shortfall * HEALTH_PER_UNPAID))
        resolver = getattr(getattr(entity, "level", None), "interaction_resolver", None)
        if resolver is not None and health_lost > 0:
            resolver.apply(InteractionContext(
                kind="damage", source_kind="stamina", source_team="environment", target=entity,
                amount=health_lost, attack_type="exertion", tags={"stamina"},
            ))

    entity._stamina_recover_at = int(now_ms) + RECOVER_DELAY_MS
    return {"paid": paid, "shortfall": shortfall, "health_lost": health_lost}


def recover(entity, stats, now_ms) -> None:
    """Move the pool back toward full. Still while dashing, dead, or inside the delay."""
    if getattr(entity, "is_dead", False):
        return
    health = getattr(entity, "health", None)
    if health is not None and float(health) <= 0:
        return
    if getattr(entity, "_dash_runtime", None) is not None:
        return
    if int(now_ms) < int(getattr(entity, "_stamina_recover_at", 0) or 0):
        return

    cap = max_stamina(stats)
    current = float(getattr(entity, "stamina", cap) or 0)
    if current >= cap:
        entity.stamina = cap
        return
    entity.stamina = min(cap, current + recover_per_tick(stats))
