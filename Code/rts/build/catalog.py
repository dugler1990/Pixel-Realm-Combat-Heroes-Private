import json
import os

from ..assets import normalize_faction_id


def _code_dir():
    return os.path.dirname(os.path.abspath(__file__))


def default_buildings_path():
    return os.path.normpath(
        os.path.join(_code_dir(), "..", "..", "..", "levels", "tmx", "rts_buildings.json")
    )


class BuildingDefinition:
    def __init__(self, building_id, data):
        self.id = str(building_id)
        self.label = str(data.get("label", self.id))
        raw_factions = data.get("factions") or []
        self.factions = [normalize_faction_id(f) for f in raw_factions]
        self.cost = dict(data.get("cost") or {})
        self.placement_requires = str(data.get("placementRequires", "")).strip()
        self.clear_duration_ms = int(data.get("clearDurationMs", 5000))
        self.build_duration_ms = int(data.get("buildDurationMs", 2000))
        spawns = data.get("spawns") or {}
        self.spawn_dropoff_kind = str(spawns.get("dropoffKind", "")).strip()
        self.spawn_node_kind = str(spawns.get("nodeKind", "")).strip()
        self.visual_phases = list(data.get("visualPhases") or data.get("visual_phases") or [])

    def matches_faction(self, faction_id):
        fid = normalize_faction_id(faction_id)
        if not self.factions:
            return True
        return fid in self.factions


_buildings_cache = None


def load_buildings(path=None):
    global _buildings_cache
    path = path or default_buildings_path()
    if _buildings_cache is not None and _buildings_cache[0] == path:
        return _buildings_cache[1]
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    buildings = {}
    if isinstance(raw, dict):
        for key, data in raw.items():
            if isinstance(data, dict):
                buildings[str(key)] = BuildingDefinition(key, data)
    _buildings_cache = (path, buildings)
    return buildings


def get_building(building_id, path=None):
    return load_buildings(path).get(str(building_id or ""))


def buildings_for_faction(faction_id, path=None):
    fid = normalize_faction_id(faction_id)
    return [b for b in load_buildings(path).values() if b.matches_faction(fid)]
