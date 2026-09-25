"""Blur the weight field so the arm/torso boundary is a gradient, not a cliff.

hide_test.py rules out the wings: the dark ragged collar survives hiding them. stretch_diag
names the torn vertices as bone_1 (torso) and bone_15/bone_25 (upper arms) - the seam *between*
the two. UniRig's weights step almost straight from one to the other, so at a 150 degree arm
raise the two sides go opposite ways and the surface everts; the mass renders dark because we
are looking at the inside of the mesh.

Corrective Smooth relaxes positions afterwards but cannot change which bone a vertex belongs
to, which is why it moved the stretch numbers and left the mass. Blurring the weights does.

Laplacian blur over the mesh graph, written by hand because bpy.ops.object.vertex_group_smooth
needs an interactive context. Writing back per vertex would be millions of API calls, so each
group is written in quantised buckets instead - one add() per bucket, error under 1/255.

The jaw is held out: it was built by hand from SAM3 masks with a measured falloff.

Writes rigged_jaw_smoothw.glb.
"""
import json
import os
import sys

import bpy
import numpy as np

RIG = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\rigged_jaw_chestfix.glb"
ROLES = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
OUT = os.path.dirname(RIG)
FACTOR = float(sys.argv[1]) if len(sys.argv) > 1 else 0.55
REPEAT = int(sys.argv[2]) if len(sys.argv) > 2 else 4
KEEP = 6                       # influences per vertex after the blur
BUCKETS = 255
MINW = 0.004

R = json.load(open(ROLES))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=RIG)
for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
    for o in list(coll.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(coll)
arm_o = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
jaw = R.get("jaw")

groups = [g for g in mesh.vertex_groups if g.name != jaw]
idx_of = {g.name: i for i, g in enumerate(groups)}
gi = {g.index: g.name for g in mesh.vertex_groups}
nv, ng = len(mesh.data.vertices), len(groups)
print("%d verts, %d groups blurred (jaw held out)" % (nv, ng), flush=True)

W = np.zeros((nv, ng), np.float32)
fixed = np.zeros(nv, np.float32)               # the jaw's share, untouched
for v in mesh.data.vertices:
    for g in v.groups:
        n = gi.get(g.group)
        if n == jaw:
            fixed[v.index] += g.weight
        elif n in idx_of:
            W[v.index, idx_of[n]] = g.weight

ne = len(mesh.data.edges)
ev = np.empty(ne * 2, np.int32)
mesh.data.edges.foreach_get("vertices", ev)
ev = ev.reshape(-1, 2)
a, b = ev[:, 0], ev[:, 1]
deg = (np.bincount(a, minlength=nv) + np.bincount(b, minlength=nv)).astype(np.float32)
deg[deg == 0] = 1.0

for it in range(REPEAT):
    S = np.empty_like(W)
    for j in range(ng):
        col = W[:, j]
        S[:, j] = (np.bincount(a, weights=col[b], minlength=nv)
                   + np.bincount(b, weights=col[a], minlength=nv))
    W = (1.0 - FACTOR) * W + FACTOR * (S / deg[:, None])
    print("  blur pass %d/%d" % (it + 1, REPEAT), flush=True)

keep_n = min(KEEP, ng)                          # drop the long tail the blur creates
cut = np.partition(W, ng - keep_n, axis=1)[:, ng - keep_n][:, None]
W[W < np.maximum(cut, MINW)] = 0.0
tot = W.sum(1) + fixed
tot[tot <= 1e-9] = 1.0
W *= ((1.0 - fixed) / tot)[:, None]

q = np.clip(np.rint(W * BUCKETS).astype(np.int16), 0, BUCKETS)
for j, g in enumerate(groups):
    g.remove(range(nv))
    col = q[:, j]
    for lvl in np.unique(col):
        if lvl <= 0:
            continue
        g.add(np.nonzero(col == lvl)[0].tolist(), float(lvl) / BUCKETS, "REPLACE")
print("wrote blurred weights, factor %.2f x%d" % (FACTOR, REPEAT), flush=True)

for img in bpy.data.images:
    if img.users and not img.packed_file:
        try:
            img.pack()
        except RuntimeError:
            pass
bpy.ops.object.select_all(action="DESELECT")
mesh.select_set(True)
arm_o.select_set(True)
bpy.context.view_layer.objects.active = arm_o
out = os.path.join(OUT, "rigged_jaw_smoothw.glb")
bpy.ops.export_scene.gltf(filepath=out, use_selection=True)
print("EXPORTED", out, flush=True)
