"""Two rigged GLBs side by side: bones, vertices, skin weights (a new character's rig steps checked on the barb).

    .venv-bpy/Scripts/python.exe tools/boss_sprite_pipeline/_checks/rig_compare.py <a.glb> <b.glb>

Prints RIG_COMPARE {json}: bone names equal, vertex counts, and over the body mesh (the one with most vertices) the
per-vertex skin weight difference (sum over bones of |a - b|, 0..2): mean, 99th percentile, max, and the share of
vertices above 0.01. Same vertex order is assumed (same source mesh); otherwise only the counts are compared.
"""
import json
import os
import sys

import bpy
import numpy as np


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.abspath(path))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    bones = [b.name for b in arm.data.bones]
    names = [g.name for g in body.vertex_groups]
    W = np.zeros((len(body.data.vertices), len(bones)), np.float32)
    col = {n: bones.index(n) for n in names if n in bones}
    for v in body.data.vertices:
        for g in v.groups:
            n = names[g.group]
            if n in col:
                W[v.index, col[n]] = g.weight
    co = np.array([v.co[:] for v in body.data.vertices], np.float32)
    return bones, W, co


a_bones, Wa, ca = load(sys.argv[1])
b_bones, Wb, cb = load(sys.argv[2])
res = {"bones_equal": a_bones == b_bones, "bones": [len(a_bones), len(b_bones)], "verts": [len(Wa), len(Wb)]}
if a_bones == b_bones and len(Wa) == len(Wb):
    res["positions_max_diff"] = float(np.abs(ca - cb).max())
    d = np.abs(Wa / np.maximum(Wa.sum(1, keepdims=True), 1e-9) - Wb / np.maximum(Wb.sum(1, keepdims=True), 1e-9)).sum(1)
    res.update(weight_diff_mean=round(float(d.mean()), 5), weight_diff_p99=round(float(np.percentile(d, 99)), 5),
               weight_diff_max=round(float(d.max()), 5), share_above_001=round(float((d > 0.01).mean()), 5))
print("RIG_COMPARE " + json.dumps(res))
