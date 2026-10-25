"""Dump the demon skeleton: parent, head/tail, length, direction, and vertex-weight mass.

Answers three questions at once:
  * is bone_14 a clavicle or the upper arm (the chest-distortion suspect)?
  * how much chest/torso mass do the shoulder bones own?
  * what does the jaw bone actually own, and where is it?
"""
import json
import os
import sys
from collections import defaultdict

import bpy

GLB = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\rigged_jaw_wingfix.glb"
ROLE = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
R = json.load(open(ROLE))

want = {R["root"], R["spine"], R["chest"], R["neck"], R["head"], R.get("jaw")}
for side in ("arm_l", "arm_r"):
    want |= {R[side]["shoulder"], R[side]["elbow"], R[side]["wrist"], R[side]["hand"]}
for side in ("leg_l", "leg_r"):
    want |= {R[side]["hip"], R[side]["knee"], R[side]["ankle"]}

rev = {}
for k in ("root", "spine", "chest", "neck", "head", "jaw"):
    if isinstance(R.get(k), str):
        rev[R[k]] = k
for side in ("arm_l", "arm_r", "leg_l", "leg_r"):
    for part, name in R[side].items():
        if isinstance(name, str):
            rev[name] = side + "." + part

print("%-10s %-14s %-10s %-22s %-22s %6s  %s" % (
    "bone", "role", "parent", "head(x,y,z)", "tail(x,y,z)", "len", "dir"), flush=True)
mw = arm.matrix_world
for b in arm.data.bones:
    if b.name not in want:
        continue
    h, t = mw @ b.head_local, mw @ b.tail_local
    d = (t - h)
    ln = d.length
    u = d.normalized() if ln > 1e-9 else d
    print("%-10s %-14s %-10s (%6.3f,%6.3f,%6.3f) (%6.3f,%6.3f,%6.3f) %6.3f  (%5.2f,%5.2f,%5.2f)" % (
        b.name, rev.get(b.name, "-"), b.parent.name if b.parent else "-",
        h.x, h.y, h.z, t.x, t.y, t.z, ln, u.x, u.y, u.z), flush=True)

# how much mesh mass does each bone own, and where does that mass sit?
gi = {vg.index: vg.name for vg in mesh.vertex_groups}
mass = defaultdict(float)
zsum = defaultdict(float)
verts = mesh.data.vertices
for v in verts:
    for g in v.groups:
        n = gi.get(g.group)
        if n in want and g.weight > 0.01:
            mass[n] += g.weight
            zsum[n] += g.weight * (mesh.matrix_world @ v.co).z
print("\n%-10s %-14s %10s %8s" % ("bone", "role", "weight-sum", "mean z"), flush=True)
for n in sorted(mass, key=lambda k: -mass[k]):
    print("%-10s %-14s %10.1f %8.3f" % (n, rev.get(n, "-"), mass[n], zsum[n] / mass[n]), flush=True)
