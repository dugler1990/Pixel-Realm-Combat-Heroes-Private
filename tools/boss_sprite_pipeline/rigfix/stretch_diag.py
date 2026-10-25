"""Which vertices actually tear, and which bone is dragging them?

Measures edge stretch (posed length / rest length) on a bad frame, then reports the dominant
vertex group of the vertices on the worst edges, plus where they sit. Beats guessing which
body part the dark shredded mass belongs to.

    .venv-bpy/Scripts/python.exe stretch_diag.py <animated.blend> <action> <frame>
"""
import os
import sys
from collections import defaultdict

import bpy
import numpy as np

BLEND = os.path.abspath(sys.argv[1])
ACTION = sys.argv[2]
FRAME = int(sys.argv[3])

bpy.ops.wm.open_mainfile(filepath=BLEND)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
sc = bpy.context.scene
ad = arm.animation_data
act = bpy.data.actions[ACTION]
ad.action = act
if hasattr(act, "slots") and hasattr(ad, "action_slot") and len(act.slots):
    ad.action_slot = act.slots[0]
sc.frame_set(FRAME)
bpy.context.view_layer.update()

nv = len(mesh.data.vertices)
rest = np.empty(nv * 3, np.float64)
mesh.data.vertices.foreach_get("co", rest)
rest = rest.reshape(-1, 3)
ne = len(mesh.data.edges)
ev = np.empty(ne * 2, np.int32)
mesh.data.edges.foreach_get("vertices", ev)
ev = ev.reshape(-1, 2)

dg = bpy.context.evaluated_depsgraph_get()
ev_obj = mesh.evaluated_get(dg)
tmp = ev_obj.to_mesh()
posed = np.empty(len(tmp.vertices) * 3, np.float64)
tmp.vertices.foreach_get("co", posed)
posed = posed.reshape(-1, 3)
ev_obj.to_mesh_clear()
print("verts %d, edges %d, posed verts %d" % (nv, ne, len(posed)), flush=True)
if len(posed) != nv:
    print("!! evaluated mesh has a different vertex count; a modifier is changing topology")
    sys.exit(1)

rl = np.linalg.norm(rest[ev[:, 0]] - rest[ev[:, 1]], axis=1)
pl = np.linalg.norm(posed[ev[:, 0]] - posed[ev[:, 1]], axis=1)
ok = rl > 1e-7
ratio = np.ones_like(rl)
ratio[ok] = pl[ok] / rl[ok]
print("edge stretch: median %.2f  p99 %.2f  p999 %.2f  max %.1f" % (
    np.median(ratio), np.percentile(ratio, 99), np.percentile(ratio, 99.9), ratio.max()), flush=True)

THRESH = max(3.0, float(np.percentile(ratio, 99.9)))
bad = ev[ratio > THRESH].ravel()
bad = np.unique(bad)
print("\n%d vertices on edges stretched more than %.1fx" % (len(bad), THRESH), flush=True)
if len(bad) == 0:
    sys.exit(0)

gi = {g.index: g.name for g in mesh.vertex_groups}
dom = defaultdict(int)
badset = set(int(i) for i in bad)
for i in badset:
    v = mesh.data.vertices[i]
    gs = {gi.get(g.group): g.weight for g in v.groups if g.weight > 0.001}
    if gs:
        dom[max(gs, key=gs.get)] += 1
print("dominant bone of the torn vertices:", flush=True)
for n in sorted(dom, key=lambda k: -dom[k])[:12]:
    print("  %-12s %6d" % (n, dom[n]), flush=True)

mw = mesh.matrix_world
P = np.array([list(mw @ mesh.data.vertices[i].co) for i in badset])
print("\nwhere they sit at rest: x %.3f..%.3f  y %.3f..%.3f  z %.3f..%.3f" % (
    P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(),
    P[:, 2].min(), P[:, 2].max()), flush=True)
print("centroid (%.3f, %.3f, %.3f)" % tuple(P.mean(0)), flush=True)
