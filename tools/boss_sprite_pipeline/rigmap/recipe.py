"""Every setting one bake uses, in one place.

A bake's settings resolve in this order, later wins:
  1. RECIPES[kind]          the proven settings for a body type (human, creature)
  2. the character row      only keys in KNOBS, for a character that must differ
  3. the panel patch        fits/<id>.json, what the user set on the page

bake_env() turns the result into the env retarget_bvh.py reads. Every knob is sent, so
nothing falls through to a default inside retarget_bvh.py, and its run.json lists each one
as "from": "env".

Human is the barb bake graded good on 2026-11-15 (barb/anim_test/retarget_ik2/run.json).
Creature is what the page already sent for the demon; nothing about him changed here.
"""
from __future__ import annotations

KNOBS = ("source", "mode", "ik_body", "bind_match", "bind_skip", "bind_ref",
         "arm_cap", "clavicle_damp", "root_loc")

RECIPES = {
    "human": {
        "source": "anunaki",
        "mode": "ik",
        "ik_body": 0.35,
        "bind_match": True,
        # roles, not bone names: bind match on the hips folds him (149 deg off on
        # barb_hit_heavy_01). The neck is always skipped by retarget_bvh.py as well.
        "bind_skip": ["root", "neck"],
        "bind_ref": "frame1",
        "arm_cap": 90.0,
        "clavicle_damp": 1.0,
        "root_loc": True,
    },
    "creature": {
        "source": "soma",
        "mode": "rot",
        "ik_body": 0.35,
        "bind_match": False,
        "bind_skip": [],
        "bind_ref": "frame1",
        "arm_cap": 35.0,
        "clavicle_damp": 1.0,
        "root_loc": True,
    },
}


def _bool(v) -> bool:
    return v in (True, 1, "1", "true", "True")


def resolve(character: dict, patch: dict | None = None) -> dict:
    """Settings for one bake, with where each came from."""
    kind = character.get("recipe")
    if kind not in RECIPES:
        raise ValueError(f"no recipe {kind!r} for {character.get('id')!r}")
    out = {k: {"value": v, "from": f"recipe:{kind}"} for k, v in RECIPES[kind].items()}
    for k in KNOBS:
        if character.get(k) is not None:
            out[k] = {"value": character[k], "from": "character"}
    patch = patch or {}
    if patch.get("arm_cap") is not None:
        out["arm_cap"] = {"value": float(patch["arm_cap"]), "from": "panel"}
    if patch.get("bind_match") is not None:
        out["bind_match"] = {"value": _bool(patch["bind_match"]), "from": "panel"}
    if patch.get("barrel_chest") is not None:
        # barrel_chest is how much sculpted shoulder width to keep; CLAVICLE_DAMP is how much
        # source clavicle rotation to copy. Opposite directions.
        kept = max(0.0, min(1.0, float(patch["barrel_chest"])))
        out["clavicle_damp"] = {"value": round(1.0 - kept, 4), "from": "panel"}
    return out


def _bone(roles: dict, role: str) -> str:
    """'root' or 'arm_l.shoulder' to the rig's bone name; a raw bone name passes through."""
    node = roles
    for part in role.split("."):
        if not isinstance(node, dict) or part not in node:
            return role
        node = node[part]
    return node if isinstance(node, str) else role


def bake_env(settings: dict, roles: dict) -> dict[str, str]:
    v = {k: s["value"] for k, s in settings.items()}
    return {
        "SOURCE": str(v["source"]),
        "RETARGET_MODE": str(v["mode"]),
        "IK_BODY": str(float(v["ik_body"])),
        "BIND_MATCH": "1" if _bool(v["bind_match"]) else "0",
        "BIND_SKIP": ",".join(_bone(roles, r) for r in v["bind_skip"]),
        "BIND_REF": str(v["bind_ref"]),
        "ARM_ELEV_CAP": str(float(v["arm_cap"])),
        "CLAVICLE_DAMP": str(float(v["clavicle_damp"])),
        "ROOT_LOC": "1" if _bool(v["root_loc"]) else "0",
    }
