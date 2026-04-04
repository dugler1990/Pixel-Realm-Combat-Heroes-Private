"""
Shared loot resolution for enemy drops, chests, and other sources.
Keeps weighted rolls in one place (see ItemSpawner.drop_from_enemy).
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

ResolvedDrop = Tuple[str, int]


def resolve_gold_drop(
    drop_info: Optional[Dict[str, Any]],
    rng: Optional[random.Random] = None,
) -> Optional[int]:
    """
    Optional separate roll for currency. If drop_info has gold_drop, roll chance once
    and return a random amount in [min, max], or None if no gold this kill.
    """
    if not drop_info:
        return None
    gd = drop_info.get("gold_drop")
    if not gd:
        return None
    rng = rng or random
    chance = float(gd.get("chance", 0))
    if chance <= 0 or rng.random() >= chance:
        return None
    lo = int(gd.get("min", 1))
    hi = int(gd.get("max", max(lo, 1)))
    if hi < lo:
        lo, hi = hi, lo
    return rng.randint(lo, hi)


def resolve_loot_table(
    drop_info: Optional[Dict[str, Any]],
    rng: Optional[random.Random] = None,
) -> List[ResolvedDrop]:
    """
    Turn item_drop_info into a flat list of (item_id, quantity) with quantity>=1 per tuple.
    Guaranteed drops are expanded first; then one weighted pick for random_drop_logic 'single'.
    No pygame / world positions.
    """
    if not drop_info:
        return []
    rng = rng or random
    resolved: List[ResolvedDrop] = []

    for drop in drop_info.get("guaranteed_drops", []):
        item_id = drop.get("item_id")
        if not item_id:
            continue
        qty = max(int(drop.get("quantity", 1)), 0)
        for _ in range(qty):
            resolved.append((str(item_id), 1))

    if drop_info.get("random_drop_logic") == "single":
        lst = drop_info.get("random_drop_list") or []
        if not lst:
            return resolved
        total_chance = sum(float(d.get("chance", 0)) for d in lst)
        if total_chance <= 0:
            return resolved
        pick = rng.random() * total_chance
        cumulative = 0.0
        for drop in lst:
            cumulative += float(drop.get("chance", 0))
            if pick <= cumulative:
                item_id = drop.get("item_id")
                if item_id:
                    resolved.append((str(item_id), 1))
                break

    return resolved
