import json
import os

from .categories import ALL_CATEGORIES


def _code_dir():
    return os.path.dirname(os.path.abspath(__file__))


def default_profiles_path():
    return os.path.normpath(
        os.path.join(_code_dir(), "..", "..", "levels", "tmx", "rts_faction_profiles.json")
    )


def default_entity_types_path():
    return os.path.normpath(
        os.path.join(_code_dir(), "..", "..", "levels", "tmx", "rts_resource_entity_types.json")
    )


class FactionProfile:
    def __init__(self, data):
        self.id = str(data.get("id", ""))
        self.display_name = str(data.get("displayName", self.id))
        self.biome = str(data.get("biome", ""))
        self.worker_unit_type = str(data.get("workerUnitType", ""))
        self.signature_resource_name = str(data.get("signatureResourceName", "Signature"))
        raw_labels = data.get("categoryDisplayNames") or {}
        self.category_display_names = {}
        if isinstance(raw_labels, dict):
            for key, label in raw_labels.items():
                if label:
                    self.category_display_names[str(key).strip().lower()] = str(label)
        self.food_upkeep_per_unit_per_min = float(data.get("foodUpkeepPerUnitPerMin", 0.5))
        inactive = data.get("inactiveCategories") or []
        self.inactive_categories = set(str(c).strip().lower() for c in inactive)
        self.active_categories = set(ALL_CATEGORIES) - self.inactive_categories
        self.resource_sources = []
        for row in data.get("resourceSources") or []:
            if isinstance(row, dict):
                self.resource_sources.append(dict(row))
        self._source_by_entity = {
            str(r.get("entityType", "")): r for r in self.resource_sources
        }

    def source_for_entity(self, entity_type):
        return self._source_by_entity.get(str(entity_type))

    def category_active(self, category):
        return str(category).lower() not in self.inactive_categories

    def display_name_for_category(self, category):
        return self.category_display_names.get(str(category).lower(), "")


_profiles_cache = None
_entity_types_cache = None


def load_faction_profiles(path=None):
    global _profiles_cache
    path = path or default_profiles_path()
    if _profiles_cache is not None and _profiles_cache[0] == path:
        return _profiles_cache[1]
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    profiles = {}
    if isinstance(raw, dict):
        for key, data in raw.items():
            if isinstance(data, dict):
                prof = FactionProfile(data)
                profiles[prof.id or key] = prof
    _profiles_cache = (path, profiles)
    return profiles


def get_profile(faction_id, path=None):
    profiles = load_faction_profiles(path)
    return profiles.get(str(faction_id))


def load_resource_entity_types(path=None):
    global _entity_types_cache
    path = path or default_entity_types_path()
    if _entity_types_cache is not None and _entity_types_cache[0] == path:
        return _entity_types_cache[1]
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    types = dict(raw) if isinstance(raw, dict) else {}
    _entity_types_cache = (path, types)
    return types


def entity_type_defaults(entity_type, path=None):
    types = load_resource_entity_types(path)
    row = types.get(str(entity_type), {})
    return {
        "maxWorkers": int(row.get("maxWorkers", 2)),
        "depletable": bool(row.get("depletable", False)),
        "respawnSeconds": float(row.get("respawnSeconds", 0)),
        "kind": str(row.get("kind", "resource")),
    }
