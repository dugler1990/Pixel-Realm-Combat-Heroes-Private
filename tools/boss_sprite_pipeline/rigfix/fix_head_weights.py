"""Give the head bone a head-sized region, and a pivot at the base of the skull.

The plan was to add a neck bone. The cross-section profile (neck_profile.py) says there is
nothing to add one to: from the shoulders to the skull the radius runs 0.135 -> 0.154 -> 0.115
with no waist at all. This demon has no neck, which is why UniRig produced none, and a bone
pushed into a solid mass with no narrowing would shear it rather than bend it.

What the profile *did* expose is the actual defect: bone_13 - the bone that is really the head -
owns vertices from z 0.130 (mid-chest) to z 0.396 (horn tips), and pivots at z 0.179, which is
shoulder height. So turning the head turns the upper chest about a point below the shoulders.

Two changes, no new bone:
  1. graded weight transfer bone_13 -> bone_12 (chest) below the skull base, so the head bone
     stops owning the trapezius. Full below LOW, none above HIGH, smoothstep between - a hard
     cut would just move the crease.
  2. move bone_13's pivot up to the skull base, so the head turns on its own base rather than
     swinging from the shoulders. The jaw hinge sits at z 0.207, so the skull starts just below.

Writes rigged_jaw_headfix.glb.
"""
import json
import os

import bpy

RIG = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\rigged_jaw_wingweights.glb"
ROLES = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
OUT = os.path.dirname(RIG)
LOW, HIGH = 0.170, 0.205          # all chest below, all head above; the jaw hinge is z 0.207

R = json.load(open(ROLES))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=RIG)
for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
    for o in list(coll.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(coll)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
head, chest = R["neck"], R["chest"]          # bone_13 is the head; the names lie, see _anatomy

vg = {g.name: g for g in mesh.vertex_groups}
if chest not in vg:
    vg[chest] = mesh.vertex_groups.new(name=chest)
gi = {g.index: g.name for g in mesh.vertex_groups}
mw = mesh.matrix_world

moved = 0.0
n = 0
for v in mesh.data.vertices:
    w = next((g.weight for g in v.groups if gi.get(g.group) == head), 0.0)
    if w <= 0.0:
        continue
    z = (mw @ v.co).z
    if z >= HIGH:
        continue
    t = 0.0 if z <= LOW else (z - LOW) / (HIGH - LOW)
    keep = t * t * (3 - 2 * t)                         # smoothstep: 0 low, 1 at the skull base
    give = w * (1.0 - keep)
    if give <= 1e-5:
        continue
    cw = next((g.weight for g in v.groups if gi.get(g.group) == chest), 0.0)
    vg[head].add([v.index], w - give, "REPLACE")
    vg[chest].add([v.index], cw + give, "REPLACE")
    moved += give
    n += 1
print("moved %.0f weight units off the head onto the chest, over %d vertices" % (moved, n), flush=True)

bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
eb = arm.data.edit_bones[head]
eb.use_connect = False                     # before moving, or it would drag the chest's tail
amw = arm.matrix_world
hz, tz = (amw @ eb.head).z, (amw @ eb.tail).z
f = max(0.0, min(0.9, (HIGH - hz) / max(tz - hz, 1e-6)))
eb.head = eb.head.lerp(eb.tail, f)
print("head pivot world z %.3f -> %.3f (%.0f%% along the bone)" % (
    hz, (amw @ eb.head).z, f * 100), flush=True)
bpy.ops.object.mode_set(mode="OBJECT")

for img in bpy.data.images:
    if img.users and not img.packed_file:
        try:
            img.pack()
        except RuntimeError:
            pass
bpy.ops.object.select_all(action="DESELECT")
mesh.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
out = os.path.join(OUT, "rigged_jaw_headfix.glb")
bpy.ops.export_scene.gltf(filepath=out, use_selection=True)
print("EXPORTED", out, flush=True)
