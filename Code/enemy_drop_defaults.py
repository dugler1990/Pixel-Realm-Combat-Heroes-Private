"""
Default probabilistic item_drop_info per monster type when spawner/JSON does not override.
Includes weighted item tiers, optional gold_drop (separate roll, random amount), + exp from monster_data.

See Settings.monster_data for exp/health; tiers are hand-tuned for ice_mage / raccoon / trash mobs.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Optional


def _tier_low() -> Dict[str, Any]:
    return {
        "random_drop_logic": "single",
        "random_drop_list": [
            {"item_id": "frozen_fish", "chance": 48},
            {"item_id": "frost_potion", "chance": 10},
            {"item_id": "ice_shard", "chance": 22},
            {"item_id": "snowflake_charm", "chance": 12},
            {"item_id": "arctic_feather", "chance": 8},
        ],
        "gold_drop": {"chance": 0.12, "min": 1, "max": 3},
    }


def _tier_mid() -> Dict[str, Any]:
    return {
        "random_drop_logic": "single",
        "random_drop_list": [
            {"item_id": "frozen_fish", "chance": 34},
            {"item_id": "frost_potion", "chance": 12},
            {"item_id": "ice_shard", "chance": 23},
            {"item_id": "snowflake_charm", "chance": 18},
            {"item_id": "arctic_feather", "chance": 13},
        ],
        "gold_drop": {"chance": 0.48, "min": 1, "max": 8},
    }


def _tier_high() -> Dict[str, Any]:
    return {
        "random_drop_logic": "single",
        "random_drop_list": [
            {"item_id": "frozen_fish", "chance": 23},
            {"item_id": "frost_potion", "chance": 12},
            {"item_id": "ice_shard", "chance": 20},
            {"item_id": "snowflake_charm", "chance": 23},
            {"item_id": "arctic_feather", "chance": 22},
        ],
        "gold_drop": {"chance": 0.55, "min": 2, "max": 14},
    }


def _tier_boss() -> Dict[str, Any]:
    return {
        "random_drop_logic": "single",
        "random_drop_list": [
            {"item_id": "frozen_fish", "chance": 12},
            {"item_id": "frost_potion", "chance": 12},
            {"item_id": "ice_shard", "chance": 18},
            {"item_id": "snowflake_charm", "chance": 28},
            {"item_id": "arctic_feather", "chance": 30},
        ],
        "gold_drop": {"chance": 0.82, "min": 6, "max": 28},
    }


# boss_key omitted from defaults — use TMX/JSON guaranteed_drops for story bosses.
DEFAULT_ITEM_DROP_BY_MONSTER_TYPE = {
    "bamboo": _tier_low(),
    "ice_ghost": _tier_low(),
    "tribey_spear": _tier_low(),
    "squid": _tier_mid(),
    "tribey_snake": _tier_mid(),
    "spirit": _tier_mid(),
    "demon_dog": _tier_mid(),
    "venom_plant": _tier_high(),
    "raccoon": _tier_high(),
    "ice_mage": _tier_boss(),
}


def get_default_item_drop_for_monster(monster_type: str) -> Optional[Dict[str, Any]]:
    """Deep copy so callers never mutate shared tables."""
    template = DEFAULT_ITEM_DROP_BY_MONSTER_TYPE.get(monster_type)
    if template is None:
        return None
    return copy.deepcopy(template)
