"""Build Tiled-style property dicts for RTS entities (sprint presets + faction JSON)."""

from .assets import normalize_faction_id
from .factions import get_profile, load_faction_profiles

NODE_KIND_ALIASES = {
    "seal_colony": "seal_hole",
    "whale": "whale_shore",
    "polar_bear_den": "walrus_shore",
}

DROPOFF_KIND_ALIASES = {
    "hunters_lodge": "smoking_rack",
    "rendering_hut": "rendering_pit",
    "storage_hut": "ice_cutting_post",
    "trade_post": "carving_lodge",
}


def _canonical_node_kind(node_kind):
    return NODE_KIND_ALIASES.get(str(node_kind or "").strip(), str(node_kind or "").strip())


def _canonical_dropoff_kind(dropoff_kind):
    return DROPOFF_KIND_ALIASES.get(
        str(dropoff_kind or "").strip(), str(dropoff_kind or "").strip()
    )


NODE_SPECS = {
    "seal_hole": {
        "type": "resource_node",
        "node_kind": "seal_hole",
        "resource_category": "food",
        "yield_amount": 40,
        "gather_duration": 20,
        "max_workers": 4,
        "depletable": False,
        "respawn_seconds": 0,
        "dropoff_kind": "smoking_rack",
        "sprite": "node_seal_hole",
        "gather_offset_y": 0,
    },
    "whale_shore": {
        "type": "resource_node",
        "node_kind": "whale_shore",
        "resource_category": "fuel",
        "yield_amount": 180,
        "gather_duration": 90,
        "max_workers": 3,
        "depletable": True,
        "respawn_seconds": 300,
        "dropoff_kind": "rendering_pit",
        "sprite": "node_whale_shore",
        "gather_offset_y": 0,
        "initial_cycles": 5,
    },
    "ice_shelf": {
        "type": "resource_node",
        "node_kind": "ice_shelf",
        "resource_category": "material",
        "yield_amount": 25,
        "gather_duration": 15,
        "max_workers": 3,
        "depletable": False,
        "respawn_seconds": 0,
        "dropoff_kind": "ice_cutting_post",
        "sprite": "node_ice_shelf",
        "gather_offset_y": 0,
    },
    "walrus_shore": {
        "type": "resource_node",
        "node_kind": "walrus_shore",
        "resource_category": "signature",
        "yield_amount": 10,
        "gather_duration": 45,
        "max_workers": 2,
        "depletable": True,
        "respawn_seconds": 120,
        "dropoff_kind": "carving_lodge",
        "sprite": "node_walrus_shore",
        "gather_offset_y": 0,
        "initial_cycles": 5,
    },
    "fruit_grove": {
        "type": "resource_node",
        "node_kind": "fruit_grove",
        "resource_category": "food",
        "yield_amount": 20,
        "gather_duration": 8,
        "max_workers": 5,
        "depletable": False,
        "respawn_seconds": 0,
        "dropoff_kind": "village_hearth",
        "sprite": "node_fruit_grove",
        "gather_offset_y": 0,
    },
    "hardwood_tree": {
        "type": "resource_node",
        "node_kind": "hardwood_tree",
        "resource_category": "fuel",
        "yield_amount": 30,
        "gather_duration": 12,
        "max_workers": 2,
        "depletable": True,
        "respawn_seconds": 60,
        "dropoff_kind": "wood_store",
        "sprite": "node_hardwood_tree",
        "gather_offset_y": 0,
        "initial_cycles": 5,
    },
    "clay_bank": {
        "type": "resource_node",
        "node_kind": "clay_bank",
        "resource_category": "material",
        "yield_amount": 20,
        "gather_duration": 10,
        "max_workers": 3,
        "depletable": False,
        "respawn_seconds": 0,
        "dropoff_kind": "clay_works",
        "sprite": "node_clay_bank",
        "gather_offset_y": 0,
    },
    "obsidian_outcrop": {
        "type": "resource_node",
        "node_kind": "obsidian_outcrop",
        "resource_category": "metal",
        "yield_amount": 15,
        "gather_duration": 25,
        "max_workers": 2,
        "depletable": True,
        "respawn_seconds": 180,
        "dropoff_kind": "knapping_stone",
        "sprite": "node_obsidian_outcrop",
        "gather_offset_y": 0,
        "initial_cycles": 5,
    },
    "spice_cluster": {
        "type": "resource_node",
        "node_kind": "spice_cluster",
        "resource_category": "signature",
        "yield_amount": 8,
        "gather_duration": 20,
        "max_workers": 3,
        "depletable": False,
        "respawn_seconds": 0,
        "dropoff_kind": "trade_hut",
        "sprite": "node_spice_cluster",
        "gather_offset_y": 0,
    },
}

DROPOFF_SPECS = {
    "smoking_rack": {
        "type": "dropoff_building",
        "dropoff_kind": "smoking_rack",
        "accepts_categories": "food",
        "sprite": "building_smoking_rack",
    },
    "rendering_pit": {
        "type": "dropoff_building",
        "dropoff_kind": "rendering_pit",
        "accepts_categories": "fuel",
        "sprite": "building_rendering_pit",
    },
    "ice_cutting_post": {
        "type": "dropoff_building",
        "dropoff_kind": "ice_cutting_post",
        "accepts_categories": "material",
        "sprite": "building_ice_cutting_post",
    },
    "carving_lodge": {
        "type": "dropoff_building",
        "dropoff_kind": "carving_lodge",
        "accepts_categories": "metal,signature",
        "sprite": "building_carving_lodge",
    },
    "village_hearth": {
        "type": "dropoff_building",
        "dropoff_kind": "village_hearth",
        "accepts_categories": "food",
        "sprite": "building_village_hearth",
    },
    "wood_store": {
        "type": "dropoff_building",
        "dropoff_kind": "wood_store",
        "accepts_categories": "fuel",
        "sprite": "building_wood_store",
    },
    "clay_works": {
        "type": "dropoff_building",
        "dropoff_kind": "clay_works",
        "accepts_categories": "material",
        "sprite": "building_clay_works",
    },
    "knapping_stone": {
        "type": "dropoff_building",
        "dropoff_kind": "knapping_stone",
        "accepts_categories": "metal",
        "sprite": "building_knapping_stone",
    },
    "trade_hut": {
        "type": "dropoff_building",
        "dropoff_kind": "trade_hut",
        "accepts_categories": "signature",
        "sprite": "building_trade_hut",
    },
}

# Legacy TMX / JSON ids resolve to the same specs as canonical names.
for _old, _new in NODE_KIND_ALIASES.items():
    if _new in NODE_SPECS and _old not in NODE_SPECS:
        legacy = dict(NODE_SPECS[_new])
        legacy["node_kind"] = _old
        NODE_SPECS[_old] = legacy

for _old, _new in DROPOFF_KIND_ALIASES.items():
    if _new in DROPOFF_SPECS and _old not in DROPOFF_SPECS:
        legacy = dict(DROPOFF_SPECS[_new])
        legacy["dropoff_kind"] = _old
        DROPOFF_SPECS[_old] = legacy


_ESKIMO_NODE_KINDS = frozenset(
    {
        "seal_hole",
        "seal_colony",
        "whale_shore",
        "whale",
        "ice_shelf",
        "walrus_shore",
        "polar_bear_den",
    }
)

_ESKIMO_DROPOFF_KINDS = frozenset(
    {
        "smoking_rack",
        "hunters_lodge",
        "rendering_pit",
        "rendering_hut",
        "ice_cutting_post",
        "storage_hut",
        "carving_lodge",
        "trade_post",
    }
)


def faction_for_entity_type(entity_type):
    et = _canonical_node_kind(entity_type)
    for fid, prof in load_faction_profiles().items():
        if prof.source_for_entity(et) or prof.source_for_entity(entity_type):
            return normalize_faction_id(fid)
    if et in _ESKIMO_NODE_KINDS:
        return "eskimo"
    return "jungle_tribe"


def resource_node_config(node_kind, faction_id=None, overrides=None):
    raw_kind = str(node_kind or "").strip()
    kind = _canonical_node_kind(raw_kind)
    cfg = dict(NODE_SPECS.get(kind, NODE_SPECS.get(raw_kind, {})))
    if not cfg:
        cfg = {
            "type": "resource_node",
            "node_kind": raw_kind,
            "resource_category": "food",
            "yield_amount": 1,
            "gather_duration": 5,
            "max_workers": 2,
            "depletable": False,
            "respawn_seconds": 0,
            "dropoff_kind": "",
            "sprite": f"node_{raw_kind}",
            "gather_offset_y": 0,
        }
    else:
        cfg["node_kind"] = raw_kind or cfg.get("node_kind", kind)
        cfg["dropoff_kind"] = _canonical_dropoff_kind(cfg.get("dropoff_kind", ""))
    fid = normalize_faction_id(faction_id or faction_for_entity_type(kind))
    cfg["faction_id"] = fid
    prof = get_profile(fid)
    if prof is not None:
        row = prof.source_for_entity(kind) or prof.source_for_entity(raw_kind)
        if row:
            cfg["resource_category"] = str(row.get("category", cfg["resource_category"])).lower()
            cfg["yield_amount"] = int(row.get("yieldAmount", cfg["yield_amount"]))
            cfg["gather_duration"] = float(row.get("gatherDuration", cfg["gather_duration"]))
            cfg["dropoff_kind"] = _canonical_dropoff_kind(
                str(row.get("dropoffBuilding", cfg["dropoff_kind"]))
            )
    if overrides:
        cfg.update(overrides)
    return cfg


def dropoff_config(dropoff_kind, faction_id=None, overrides=None):
    raw_kind = str(dropoff_kind or "").strip()
    kind = _canonical_dropoff_kind(raw_kind)
    cfg = dict(DROPOFF_SPECS.get(kind, DROPOFF_SPECS.get(raw_kind, {})))
    if not cfg:
        cfg = {
            "type": "dropoff_building",
            "dropoff_kind": raw_kind,
            "accepts_categories": "food",
            "sprite": f"building_{raw_kind}",
        }
    else:
        cfg["dropoff_kind"] = kind
    if faction_id:
        cfg["faction_id"] = normalize_faction_id(faction_id)
    elif "faction_id" not in cfg:
        cfg["faction_id"] = (
            "eskimo" if kind in _ESKIMO_DROPOFF_KINDS or raw_kind in _ESKIMO_DROPOFF_KINDS
            else "jungle_tribe"
        )
    if overrides:
        cfg.update(overrides)
    return cfg
