"""Vertices glTF parks on "neutral_bone" (no real joint) take the weights of their nearest weighted
neighbour (explode2/fix_neutral_bone.py). Barb: 752 loincloth vertices streaked behind him once the root
travelled (run, backstep).
"""
from __future__ import annotations

NAME = "rehome_orphans"
DOC = "move vertices off glTF's neutral_bone onto their nearest weighted neighbours"
KIND = "weights"
LANE = "local"
SETTINGS = []
CHECKS = {"weights": [("neutral_bone_verts", "==", 0, True), ("unweighted_verts", "==", 0, True)]}


def run(ctx) -> dict:
    out = ctx.dir / "rig.glb"
    ctx.blender([str(ctx.pipe / "explode2" / "fix_neutral_bone.py"), ctx.input_glb, str(out)], expect="FIX_OK")
    ctx.check("weights", ctx.measure("weights", out))
    return {"glb": out, "roles": ctx.input_roles}
