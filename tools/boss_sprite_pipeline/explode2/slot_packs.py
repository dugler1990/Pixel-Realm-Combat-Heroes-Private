"""One clips blend per armour slot: the slot's mesh on the clips' armature, rigid on the bones it sits on.

    .venv-bpy/Scripts/python.exe slot_packs.py <clips.blend> <body_rigged.glb> <roles.json> <slots_parts.glb> <out_dir>

<clips.blend>: player_clips.py output (armature + idle / move / attack), the skeleton the slots go on.
<body_rigged.glb>: the body on that skeleton (rig_game); each slot vertex takes the bone weights of the body skin
nearest to it, then the slot's rule makes it rigid (plates do not stretch with the skin):

    chest      chest bone 100 %              belt     root 100 %           pants_*  thigh 100 %
    shoulder_* collarbone or upper arm       gauntlet_* forearm or hand     boot_*   shin, foot or toes
    loincloth  hips at the waist, up to 50 % thighs at the hem (explode_common.piece_weights, as the skirt)
    (each vertex one bone where two or three are listed: the one whose skin weighs most under it)

Writes <out_dir>/<slot>.blend (armature + that slot only, for export_mesh_runtime.py) and slot_packs.json.
"""
import json
import os
import sys

import bpy
import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "explode"))
from explode_common import piece_weights  # noqa: E402

CLIPS, BODY, ROLES, SLOTS, OUT = (os.path.abspath(a) for a in sys.argv[1:6])
os.makedirs(OUT, exist_ok=True)
K = 4
roles = json.load(open(ROLES))


def log(*a):
    print("[slot_packs]", *a, flush=True)


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    return [o for o in bpy.data.objects if o not in before]


def world_verts(o):
    V = np.empty(len(o.data.vertices) * 3, np.float32)
    o.data.vertices.foreach_get("co", V)
    V = V.reshape(-1, 3).astype(np.float64)
    M = np.array(o.matrix_world)
    return V @ M[:3, :3].T + M[:3, 3]


def rule(slot):
    """(allowed bones, or the name explode_common.piece_weights knows) for a slot."""
    base, side = (slot[:-2], slot[-1]) if slot[-2:] in ("_l", "_r") else (slot, None)
    a, g = (roles.get(f"arm_{side}"), roles.get(f"leg_{side}")) if side else (None, None)
    return {"chest": [roles["chest"]], "belt": [roles["root"]], "loincloth": "loincloth",
            "shoulder": [a["shoulder"], a["elbow"]] if a else None, "gauntlet": [a["wrist"], a["hand"]] if a else None,
            "pants": [g["hip"]] if g else None, "boot": [g["knee"], g["ankle"], g["foot"]] if g else None}[base]


bpy.ops.wm.open_mainfile(filepath=CLIPS)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for o in [o for o in bpy.data.objects if o.type == "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)

new = import_glb(BODY)
body = max((o for o in new if o.type == "MESH" and len(o.vertex_groups)), key=lambda o: len(o.data.vertices))
B = world_verts(body)
gnames = [g.name for g in body.vertex_groups]
W = np.zeros((len(B), len(gnames)), np.float32)
for v in body.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
H = float(np.ptp(B[:, 2]))
tree = cKDTree(B)
for o in new:
    bpy.data.objects.remove(o, do_unlink=True)
log("body", len(B), "verts,", len(gnames), "groups")

new = import_glb(SLOTS)
slots = [o for o in new if o.type == "MESH"]
for o in new:
    if o.type != "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
report = {}
for o in slots:
    name = o.name.split(".")[0]
    mw = o.matrix_world.copy()
    o.data.transform(mw)
    o.parent = None
    o.matrix_world.identity()
    P = world_verts(o)
    d, idx = tree.query(P, k=K)
    inv = 1.0 / np.maximum(d, 1e-9)
    Wa = (W[idx] * inv[:, :, None]).sum(1) / inv.sum(1, keepdims=True)
    r = rule(name)
    if r == "loincloth":
        out = piece_weights("loincloth", P, Wa, roles, gnames, H)
    else:
        cols = [gnames.index(b) for b in r]
        pick = np.array(cols)[np.argmax(Wa[:, cols], 1)]
        out = np.zeros_like(Wa)
        out[np.arange(len(P)), pick] = 1
    o.vertex_groups.clear()
    used = np.nonzero(out.sum(0) > 0)[0]
    for j in used:
        g = o.vertex_groups.new(name=gnames[j])
        for w in np.unique(out[:, j][out[:, j] > 0]):
            g.add(np.nonzero(out[:, j] == w)[0].tolist(), float(w), "REPLACE")
    for m in [m for m in o.modifiers if m.type == "ARMATURE"]:
        o.modifiers.remove(m)
    mod = o.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    o.parent = arm
    o.matrix_parent_inverse = arm.matrix_world.inverted()
    o.name = o.data.name = name
    report[name] = {"verts": len(P), "faces": len(o.data.polygons),
                    "bones": {gnames[j]: int((out[:, j] > 0).sum()) for j in used}}
    log(name, report[name])

all_blend = os.path.join(OUT, "_all_slots.blend")
bpy.ops.wm.save_as_mainfile(filepath=all_blend)
for name in report:
    bpy.ops.wm.open_mainfile(filepath=all_blend)
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name != name]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, f"{name}.blend"))
os.remove(all_blend)
json.dump(report, open(os.path.join(OUT, "slot_packs.json"), "w"), indent=1)
log("SLOT_PACKS_OK", sorted(report))
