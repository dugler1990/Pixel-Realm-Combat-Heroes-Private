"""Move a bone's pivot (head); direction, length and weights stay (rigfix/fix_jaw_hinge.py, generalised).

Demon jaw 2026-09-26: the hinge floated at z 0.207 above the jaw's own span 0.118..0.193, so a close
swung it back and up; lowered to the jaw's top (0.193). geometry_top = that rule: a high percentile
of the z of the vertices weighted >= 0.5 to the bone. geometry_bottom: the sole of a foot or ankle.
"""
from __future__ import annotations

from ...settings import Setting

NAME = "move_pivot"
DOC = "move one bone's pivot; direction, length and weights unchanged"
KIND = "bone_set"
LANE = "local"
SETTINGS = [
    Setting("role", "str", "the bone's role, e.g. jaw, ankle.L"),
    Setting("target", "choice", "geometry_top: top of its own vertices; geometry_bottom: their bottom (a sole); "
            "point: the given world point", default="geometry_top",
            choices=("geometry_top", "geometry_bottom", "point")),
    # 100 reproduces the demon hinge fix (0.1922 vs the hand value 0.193; 97 gave 0.181)
    Setting("percentile", "float", "how far into the vertex span counts as the top/bottom", default=100.0,
            min=50.0, max=100.0),
    Setting("point", "str", "x,y,z world, for target point", default="", required=False),
]
CHECKS = {"pivot": [("moved", ">", 0.0, True)]}


def run(ctx) -> dict:
    s = ctx.settings
    bone = ctx.input_roles.get(s["role"])
    if not bone:
        raise ValueError(f"the rig has no role {s['role']!r}")
    params = {"bone": bone, "target": s["target"], "percentile": s["percentile"]}
    if s["target"] == "point":
        params["point"] = [float(x) for x in s["point"].split(",")]
    out, numbers = ctx.op("move_pivot", params)
    ctx.check("pivot", numbers)
    return {"glb": out, "roles": ctx.input_roles}
