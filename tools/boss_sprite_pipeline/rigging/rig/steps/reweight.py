"""New skin weights, same skeleton (rigfix/rig_reweight.py).

heat: voxel-remesh a watertight proxy (voxel = % of height), Blender bone-heat weights on it, transfer to
the real mesh, top 4, normalise. smooth: diffuse the existing weights N times. Barb 2026-11-01: heat 0.5
picked (clean in 6 poses, 33-43 s); smooth 150 a close second (4.6 min); UniRig's own crinkles
(PROCESS_rigfix.md). Armour shells need voxel 2.0 (0.5 does not fuse; PROCESS_explode2.md).
"""
from __future__ import annotations

from ...settings import Setting

NAME = "reweight"
DOC = "new skin weights on the same skeleton: bone heat on a voxel proxy, or smoothing"
KIND = "weights"
LANE = "local"
SETTINGS = [
    Setting("method", "choice", "heat: bone heat on a voxel proxy; smooth: diffuse the current weights",
            default="heat", choices=("heat", "smooth")),
    Setting("param", "float", "heat: voxel size, % of height (0.5 picked; 2.0 for armour). smooth: iterations",
            default=0.5, min=0.1, max=500.0),
]
# neutral_bone_verts is info: rehome_orphans follows a reweight. 2026-11-21, heat 0.5 on barb v1
# (barb_final_nb): 146,277 verts on neutral_bone; the original heat run on the painted barb left 752.
CHECKS = {"weights": [("unweighted_verts", "==", 0, True), ("edges_jump_over_0_3_pct", "<=", 1.95, False),
                      ("neutral_bone_verts", "==", 0, False)]}


def run(ctx) -> dict:
    out = ctx.dir / "rig.glb"
    ctx.blender([str(ctx.pipe / "rigfix" / "rig_reweight.py"), ctx.input_glb, str(out), ctx.settings["method"],
                 str(ctx.settings["param"])], expect="REWEIGHT_OK")
    ctx.check("weights", ctx.measure("weights", out))
    return {"glb": out, "roles": ctx.input_roles}
