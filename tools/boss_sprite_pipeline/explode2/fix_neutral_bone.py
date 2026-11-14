"""Rehome the vertices a glTF rig parks on "neutral_bone".

    .venv-bpy/Scripts/python.exe fix_neutral_bone.py <rigged.glb> <out.glb>

glTF export gives vertices with no real joint a "neutral_bone" that nothing animates. On barb_final 752
loincloth vertices sit on it: in-place clips hide it, but once the root travels (run, backstep) they stay
behind and stretch into a streak from his hips. Each such vertex takes the weights of its nearest vertex
on real bones; the neutral_bone group is removed. Exports the mesh and armature (same materials).
"""
import os
import sys

import bpy
import numpy as np
from scipy.spatial import cKDTree

SRC, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
names = [g.name for g in body.vertex_groups]
nb = names.index("neutral_bone")
n = len(body.data.vertices)
W = np.zeros((n, len(names)), np.float32)
for v in body.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
bad = W.argmax(1) == nb
co = np.empty(n * 3, np.float32)
body.data.vertices.foreach_get("co", co)
co = co.reshape(-1, 3)
good = np.nonzero(~bad & (W[:, nb] < 1e-6))[0]
_, idx = cKDTree(co[good]).query(co[bad], workers=-1)
W[bad] = W[good[idx]]
for gi, g in enumerate(body.vertex_groups):
    if gi == nb:
        continue
    sel = np.nonzero(bad & (W[:, gi] > 1e-4))[0].tolist()
    if sel:
        g.remove(sel)
        for i in sel:
            g.add([i], float(W[i, gi]), "REPLACE")
body.vertex_groups.remove(body.vertex_groups[nb])
print(f"rehomed {int(bad.sum())} vertices from neutral_bone onto their nearest weighted neighbours", flush=True)
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=OUT, use_selection=True)
print("FIX_OK", OUT, flush=True)
