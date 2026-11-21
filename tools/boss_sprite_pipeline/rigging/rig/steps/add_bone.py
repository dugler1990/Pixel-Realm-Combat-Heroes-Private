"""Add a bone the rig lacks. One step, three placements; the weight rule is always distance, never a box.

joint    - where the source clip's joint is, relative to its parent joint, at the clip's first frame,
           scaled by target / source height. No weights (the region stays on the parent). Built.
geometry - from vertex extremes (the demon's wings, NOTES_rig_jaw_sam3.md section 2). Not built yet.
sam      - lit head renders (front 15 deg elevation, side yaw 90), local SAM3, union of instances by
           height band, pixels -> vertices by a world-position render, distance-falloff weights
           (face_parts.py). Not built yet: the head render, the SAM3 driver and the check sheet were
           scratch files and are lost, and face_parts.py is in demon units (metres, fixed head camera).

Kimodo never moves Jaw or the eyes (<= 1.1 / 3.7 deg over 40 clips), so a bone placed here is posed
(jaw_closed) or procedural, not driven by a clip.
"""
from __future__ import annotations

from ... import paths, sources
from ...settings import Setting

NAME = "add_bone"
DOC = "add a bone the rig lacks (jaw, eyes, wings): placement joint / geometry / sam"
KIND = "bone_set"
LANE = "local"
SETTINGS = [
    Setting("role", "str", "role of the new bone, e.g. jaw, eye.L"),
    Setting("parent_role", "str", "role of its parent", default="head"),
    Setting("placement", "choice", "joint: from the source clip; geometry / sam: not built yet",
            default="joint", choices=("joint", "geometry", "sam")),
    Setting("bvh", "path", "joint placement: clip whose first frame gives the joint offset",
            default="bosses/kimodo_new_blender/walk_v1_00.bvh"),
    Setting("source", "choice", "the clip's skeleton", default="soma", choices=tuple(sources.SOURCES)),
    Setting("length_frac", "float", "bone length as a share of the parent-to-joint offset", default=0.3,
            min=0.05, max=2.0),
]
CHECKS = {"bone": [("added", "==", 1, True)]}


def run(ctx) -> dict:
    s = ctx.settings
    if s["role"] in ctx.input_roles:
        raise ValueError(f"the rig already has {s['role']}: {ctx.input_roles[s['role']]}")
    parent = ctx.input_roles.get(s["parent_role"])
    if not parent:
        raise ValueError(f"the rig has no role {s['parent_role']!r}")
    if s["placement"] != "joint":
        raise NotImplementedError(f"placement {s['placement']!r} is not built yet (PLAN_rig_library.md order 6)")
    table = sources.get(s["source"]).JOINTS
    joint_of = {role: j for j, role in table.items()}
    if s["role"] not in joint_of or s["parent_role"] not in joint_of:
        raise ValueError(f"{s['source']} has no joint for {s['role']} or {s['parent_role']}")
    name = s["role"].replace(".", "_")
    out, numbers = ctx.op("add_bone_joint", {
        "name": name, "parent": parent, "joint": joint_of[s["role"]], "parent_joint": joint_of[s["parent_role"]],
        "bvh": str(paths.resolve(s["bvh"])), "length_frac": s["length_frac"]})
    ctx.check("bone", {"added": 1, **numbers})
    roles = dict(ctx.input_roles)
    roles[s["role"]] = name
    return {"glb": out, "roles": roles}
