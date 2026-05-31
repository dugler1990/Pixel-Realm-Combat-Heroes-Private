from .assets import normalize_faction_id

_FACTION_MONSTER = {
    "eskimo": "eskimo_worker",
    "jungle_tribe": "jungle_worker",
}

_SPRITE_MONSTER = {
    "worker_eskimo": "eskimo_worker",
    "worker_jungle": "jungle_worker",
    "chief_eskimo": "eskimo_chief",
    "chief_jungle": "jungle_chief",
}


def monster_name_for_faction(faction_id, sprite_key=""):
    key = str(sprite_key or "").strip()
    if key in _SPRITE_MONSTER:
        return _SPRITE_MONSTER[key]
    fid = normalize_faction_id(faction_id)
    if fid == "jungle_tribe":
        return "jungle_worker"
    return _FACTION_MONSTER.get(fid, "eskimo_worker")
