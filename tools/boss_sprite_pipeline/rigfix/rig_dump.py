"""Dump any rigged GLB's skeleton - names, parents, positions, weight mass. No roles file needed.

    .venv-bpy/Scripts/python.exe rig_dump.py <rigged.glb>

skel_dump.py answers questions about the demon and needs its bone_roles.json to already exist.
For a brand-new UniRig output there is no roles file yet, and writing one by hand means first
seeing what UniRig actually produced.
"""
import os
import sys
from collections import defaultdict

import bpy

GLB = os.path.abspath(sys.argv[1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
arm, mesh = arms[0], meshes[0]
tw = arm.matrix_world

mass = defaultdict(float)
gname = {g.index: g.name for g in mesh.vertex_groups}
for v in mesh.data.vertices:
    for g in v.groups:
        if g.weight > 0.01:
            mass[gname.get(g.group, "?")] += g.weight

print("armature %s  bones %d  mesh verts %d" % (arm.name, len(arm.data.bones), len(mesh.data.vertices)))
print("%-22s %-22s %7s %7s %7s %7s %9s" % ("bone", "parent", "hx", "hy", "hz", "len", "weight"))


def walk(b, depth=0):
    h = tw @ b.head_local
    t = tw @ b.tail_local
    print("%-22s %-22s %7.3f %7.3f %7.3f %7.3f %9.0f" % (
        ("  " * depth + b.name)[:22], (b.parent.name if b.parent else "-")[:22],
        h.x, h.y, h.z, (t - h).length, mass.get(b.name, 0.0)))
    for c in sorted(b.children, key=lambda c: -(tw @ c.head_local).z):
        walk(c, depth + 1)


for b in arm.data.bones:
    if b.parent is None:
        walk(b)
