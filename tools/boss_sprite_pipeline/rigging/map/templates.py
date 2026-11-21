"""Templates: the mapping decisions a new character file is copied from. Copied once; editing a
template later does not change any character.

human = the barb bake graded good on 2026-11-15 (barb/anim_test/retarget_ik2/run.json).
demon = what the page sent the demon before 2026-11-21: rot, bind off, arm cap 35. Jaw closed 14
        (TARGETS["demon"], set with the hinge fix; the old roles file said 18).
"""
from __future__ import annotations

import copy

TEMPLATES = {
    "human": {
        "roles_style": "anun",
        "map": {
            "mode": "ik",
            "ik_body": 0.35,
            "root_loc": True,
            "reference_pose": "frame1",
            "bind_default": True,
            # bind match on the hips folds him (149.3 deg on barb_hit_heavy_01); the neck was
            # always skipped in the old code
            "bind": {"root": False, "neck": False},
            "arm_cap": 90.0,
            "clavicle_damp": 1.0,
            "jaw_closed": 0.0,
        },
    },
    "demon": {
        "roles_style": "demon_hand",
        "map": {
            "mode": "rot",
            "ik_body": 0.35,
            "root_loc": True,
            "reference_pose": "frame1",
            "bind_default": False,
            # the old code always skipped the key "neck", which on him is the skull
            "bind": {"head": False},
            "arm_cap": 35.0,
            "clavicle_damp": 1.0,
            "jaw_closed": 14.0,
        },
    },
}


def get(name: str) -> dict:
    if name not in TEMPLATES:
        raise ValueError(f"template {name!r}, have {sorted(TEMPLATES)}")
    return copy.deepcopy(TEMPLATES[name])
