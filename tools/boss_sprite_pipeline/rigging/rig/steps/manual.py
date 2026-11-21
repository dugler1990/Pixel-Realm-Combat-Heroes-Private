"""A hand-made rig (Blender by hand, a repaint, an outside tool) enters the chain here, with the reason.

The glb is copied into the version folder. Roles carry over from the input unless a roles file is given
(an anun_roles.py-style file, converted). Kind is decided by comparing the bone set with the input.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from ... import paths
from ... import roles as R
from ...settings import Setting

NAME = "manual"
DOC = "import a hand-edited glb, with who made it and why"
KIND = "auto"
LANE = "local"
SETTINGS = [
    Setting("glb", "path", "the hand-made rigged glb (generated-relative or absolute)"),
    Setting("reason", "str", "who made it and why"),
    Setting("roles_file", "path", "optional anun_roles-style roles file; empty = keep the input's roles",
            default="", required=False),
]
CHECKS = {"weights": [("unweighted_verts", "==", 0, True)]}


def run(ctx) -> dict:
    src = paths.resolve(ctx.settings["glb"])
    if not Path(src).is_file():
        raise FileNotFoundError(src)
    out = ctx.dir / "rig.glb"
    shutil.copy(src, out)
    roles = ctx.input_roles
    if ctx.settings.get("roles_file"):
        roles = R.canonical(json.loads(paths.resolve(ctx.settings["roles_file"]).read_text(encoding="utf-8")),
                            "anun")
    ctx.check("weights", ctx.measure("weights", out))
    return {"glb": out, "roles": roles}
