"""The character file: decisions only. generated/bosses/characters/<id>/character.json

{"id", "template", "rig": N, "map": {...MAP settings...}, "note"}

Results (pose-check angles, proportions) are never stored here; they live in each bake's run.json.
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import paths
from ..settings import Setting, SettingError, resolve as _resolve
from . import pairs, templates

MAP_SETTINGS = [
    Setting("mode", "choice", "ik: hands and feet placed by two-bone IK; rot: rotation copy only",
            choices=("ik", "rot")),
    Setting("ik_body", "float", "IK target blend: 0 limb-anchored (= rotation copy), 1 hip-anchored",
            min=0.0, max=1.0),
    Setting("root_loc", "bool", "root follows the clip's travel; off pins it and takes rotation only"),
    Setting("reference_pose", "str", "pose the bind is measured against: frame1, tpose, or an idle_pose.json path"),
    Setting("bind_default", "bool", "bind match for every paired role unless listed in bind"),
    Setting("bind", "roles_bool", "per-role bind match, overriding bind_default"),
    Setting("bind_axis", "choice", "bone_y: aim each bone's own +Y axis (graded barb bake); joint: aim the "
            "joint-to-joint segment (experiment 1: binds the barb's hips without folding them)",
            default="bone_y", choices=("bone_y", "joint")),
    Setting("arm_cap", "float", "highest the upper arm may point above horizontal; 90 = open",
            min=0.0, max=120.0, unit="deg"),
    Setting("clavicle_damp", "float", "share of the source clavicle rotation copied; 1 = all",
            min=0.0, max=1.0),
    Setting("jaw_closed", "float", "degrees the jaw is held shut when the rig has a jaw; 0 = rest",
            min=0.0, max=60.0, unit="deg"),
]


def path(cid: str) -> Path:
    return paths.character_dir(cid) / "character.json"


def exists(cid: str) -> bool:
    return path(cid).is_file()


def load(cid: str) -> dict:
    return json.loads(path(cid).read_text(encoding="utf-8"))


def save(char: dict) -> None:
    p = path(char["id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    validate(char)
    p.write_text(json.dumps(char, indent=1), encoding="utf-8")


def all_ids() -> list[str]:
    root = paths.characters()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "character.json").is_file())


def create(cid: str, template: str, rig: int, note: str = "") -> dict:
    t = templates.get(template)
    char = {"id": cid, "template": template, "rig": rig, "map": t["map"],
            "note": note}
    save(char)
    return char


def validate(char: dict) -> None:
    for key in ("id", "template", "rig", "map"):
        if key not in char:
            raise SettingError(f"character file: missing {key}")
    _resolve(MAP_SETTINGS, [("character", char["map"])])


def resolve(char: dict, source: str) -> dict:
    """Every map setting for one bake of `source` onto this character, with where each came from.
    The pair exception merges into the per-role bind table; nothing else falls back anywhere."""
    out = _resolve(MAP_SETTINGS, [("character", char["map"])])
    pair = pairs.get(source, char["id"])
    if pair.get("bind"):
        merged = dict(out["bind"]["value"])
        merged.update(pair["bind"])
        out["bind"] = {"value": merged, "from": f"character+pair:{source}"}
    return out


def bind_flags(resolved: dict, roles: list[str]) -> dict[str, bool]:
    default = resolved["bind_default"]["value"]
    table = resolved["bind"]["value"]
    return {r: bool(table.get(r, default)) for r in roles}


def set_map(cid: str, patch: dict) -> dict:
    """Panel edit: patch the map decisions, validate, save."""
    char = load(cid)
    m = dict(char["map"])
    for k, v in patch.items():
        if k == "bind" and isinstance(v, dict):
            b = dict(m.get("bind") or {})
            for role, flag in v.items():
                if flag is None:
                    b.pop(role, None)
                else:
                    b[role] = bool(flag)
            m["bind"] = b
        else:
            m[k] = v
    char["map"] = m
    save(char)
    return char
