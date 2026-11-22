"""A character's shared settings: tools/boss_sprite_pipeline/outfits/<character>/character.json.

What every outfit of one character uses (its rig, roles, clips, game entry). outfit.py merges it under each outfit
file; retarget_bvh.py and player_clips.py read their parts of it. No defaults: a missing field stops with its name.
Fields: outfit_fields.py. Stdlib only (Blender's python imports it too).
"""
from __future__ import annotations

import json
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
OUTFITS = TOOLS / "outfits"
FILE = "character.json"


class Missing(SystemExit):
    """A field a step needs is not in the character file."""


def path(character: str) -> Path:
    return OUTFITS / character / FILE


def load(character: str) -> dict:
    p = path(character)
    if not p.is_file():
        raise Missing(f"no character file {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def need(c: dict, character: str, dotted: str):
    """c's value at a dotted name ("clips.attack"), else stop naming the field."""
    v = c
    for part in dotted.split("."):
        if not isinstance(v, dict) or part not in v:
            raise Missing(f"outfits/{character}/{FILE} has no {dotted}")
        v = v[part]
    return v


def retarget_target(character: str) -> dict | None:
    """retarget_bvh.py's target row for a character with a file and a "retarget" block (its rig is rig_game, the
    animated game rig); None otherwise (the bosses keep their rows in retarget_bvh.TARGETS)."""
    if not path(character).is_file():
        return None
    c = load(character)
    if "retarget" not in c:
        return None
    return {**c["retarget"], "rig": need(c, character, "rig_game"), "roles": need(c, character, "roles")}


def clip_choice(character: str) -> dict:
    """player_clips.py's source clips: idle, move, attack names and the attack's frame ranges."""
    c = load(character)
    return {k: need(c, character, f"clips.{k}") for k in ("idle", "move", "attack", "attack_frames")}
