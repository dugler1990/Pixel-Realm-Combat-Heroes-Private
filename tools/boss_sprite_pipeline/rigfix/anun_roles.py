"""Derive bone_roles.json from a UniRig skeleton by walking it, for each Anunnaki model.

    .venv-bpy/Scripts/python.exe anun_roles.py <rigged.glb> <out.json>

The demon's roles were read off a drawn skeleton by hand and came out off by one on the arms
(see its bone_roles.json `_anatomy`). That is worth not repeating four more times, and UniRig
does not promise the same bone numbering between models, so the roles are found from the
skeleton's own shape instead of assumed:

  root      the parentless bone
  legs      root's two children whose chains descend
  torso     root's remaining child, followed up until a bone has three children - that fork is
            the chest, because the neck and both clavicles hang off it
  neck/head the fork's child nearest the midline, then its child
  arms      the fork's other two children, outward; +X is the character's left (he faces -Y)

Unlike the demon these rigs have a real neck and a fourth torso bone, so they get `spine2` and
a true `neck`/`head` split - slots the demon had nothing to fill.
"""
import json
import os
import sys
from collections import defaultdict

import bpy

GLB, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
tw = arm.matrix_world

mass = defaultdict(float)
gname = {g.index: g.name for g in mesh.vertex_groups}
for v in mesh.data.vertices:
    for g in v.groups:
        if g.weight > 0.01:
            mass[gname.get(g.group, "?")] += g.weight


def head(b):
    return tw @ b.head_local


def chain(b, limit=8):
    """Follow single-file descendants, always taking the heaviest child."""
    out = [b.name]
    while b.children and len(out) < limit:
        b = max(b.children, key=lambda c: mass.get(c.name, 0.0))
        out.append(b.name)
    return out


root = next(b for b in arm.data.bones if b.parent is None)
kids = list(root.children)
legs = sorted([c for c in kids if head(c).z < head(root).z + 0.02],
              key=lambda c: -head(c).x)                       # +X first = his left
torso = [c for c in kids if c not in legs]
if len(legs) != 2 or len(torso) != 1:
    print("UNEXPECTED root fan: legs=%d torso=%d" % (len(legs), len(torso)))
    for c in kids:
        print("   ", c.name, "%.3f %.3f %.3f" % tuple(head(c)))
    sys.exit(1)

# up the torso until the bone that forks into neck + two clavicles
spine = [torso[0]]
b = torso[0]
while len(b.children) < 3 and b.children:
    b = max(b.children, key=lambda c: head(c).z)
    spine.append(b)
chest = spine[-1]
fork = list(chest.children)
neck = min(fork, key=lambda c: abs(head(c).x))
clavs = sorted([c for c in fork if c is not neck], key=lambda c: -head(c).x)
if len(clavs) != 2:
    print("UNEXPECTED chest fork:", [c.name for c in fork])
    sys.exit(1)

neck_chain = chain(neck, 3)
roles = {
    "_source": "%s - UniRig, roles derived geometrically by anun_roles.py. 'l' = his left = +X "
               "(he faces -Y). Unlike the demon these names are literal: neck is a neck." %
               os.path.basename(GLB),
    "root": root.name,
    "spine": spine[0].name,
    "chest": chest.name,
    "neck": neck_chain[0],
    "head": neck_chain[1] if len(neck_chain) > 1 else neck_chain[0],
}
if len(spine) > 2:
    roles["spine2"] = spine[1].name          # the demon had no fourth torso bone

for side, clav in zip(("arm_l", "arm_r"), clavs):
    c = chain(clav, 5)
    roles[side] = {"shoulder": c[0], "elbow": c[1], "wrist": c[2], "hand": c[3] if len(c) > 3 else c[2]}
for side, leg in zip(("leg_l", "leg_r"), legs):
    c = chain(leg, 5)
    roles[side] = {"hip": c[0], "knee": c[1], "ankle": c[2], "foot": c[3] if len(c) > 3 else c[2]}

json.dump(roles, open(OUT, "w"), indent=1)
print("bones %d" % len(arm.data.bones))
for k in ("root", "spine", "spine2", "chest", "neck", "head"):
    if k in roles:
        n = roles[k]
        print("  %-7s %-9s z=%.3f w=%.0f" % (k, n, head(arm.data.bones[n]).z, mass.get(n, 0)))
for k in ("arm_l", "arm_r", "leg_l", "leg_r"):
    print("  %-7s %s" % (k, " -> ".join(roles[k][j] for j in
                                        (("shoulder", "elbow", "wrist", "hand") if "arm" in k
                                         else ("hip", "knee", "ankle", "foot")))))
print("ROLES_OK", OUT)
