"""Label a UniRig skeleton by walking it (rigfix/anun_roles.py): the root fan gives legs vs torso, the
first bone with three children is the chest, +X is his left. Never hand-map UniRig bones: counts and
numbering differ per model (28/40/28/46 on the anunaki). A per-role override patches the result.
"""
from __future__ import annotations

import json

from ... import roles as R
from ...settings import Setting

NAME = "roles_walk"
DOC = "label bones by walking the skeleton (anun_roles.py); overrides patch single roles"
KIND = "bone_set"          # roles change what a bake drives
LANE = "local"
SETTINGS = [
    Setting("overrides", "roles_map", "role -> bone name, applied after the walk", default={}, required=False),
]
CHECKS = {"required_roles": [("missing", "==", 0, True)]}


def run(ctx) -> dict:
    out = ctx.dir / "anun_roles.json"
    ctx.blender([str(ctx.pipe / "rigfix" / "anun_roles.py"), ctx.input_glb, str(out)], expect="ROLES_OK")
    roles = R.canonical(json.loads(out.read_text(encoding="utf-8")), "anun")
    for role, bone in (ctx.settings.get("overrides") or {}).items():
        roles[role] = bone
    missing = [r for r in R.ROLES if r not in roles and r not in R.FACE]
    ctx.check("required_roles", {"missing": len(missing), "roles": sorted(roles), "missing_roles": missing})
    return {"glb": None, "roles": roles}
