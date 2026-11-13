"""Put another body (same skeleton) into a clips blend, keeping its actions.

    .venv-bpy/Scripts/python.exe swap_body.py <clips.blend> <body.glb> <out.blend>

<clips.blend> is a player_clips.py output (armature + idle / move / attack). <body.glb> is a mesh rigged
on the same skeleton (e.g. explode2's outfit_skeleton.py output, painted): same bone names and rest
pose. The old body meshes are deleted, the new one is joined into one mesh, bound to the clips'
armature, and the result saved; export_mesh_runtime.py then packs it like any other.
"""
import os
import sys

import bpy
import numpy as np

SRC, BODY, OUT = (os.path.abspath(a) for a in sys.argv[1:4])
REST_TOL = 1e-3          # model units (he is ~1.3 tall)

bpy.ops.wm.open_mainfile(filepath=SRC)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
old = [o for o in bpy.data.objects if o.type == "MESH"]
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=BODY)
new_objs = [o for o in bpy.data.objects if o not in before]
new_arm = next(o for o in new_objs if o.type == "ARMATURE")
meshes = [o for o in new_objs if o.type == "MESH" and len(o.vertex_groups)]   # not the importer's bone shapes
others = [o for o in new_objs if o not in meshes]

# Same skeleton: names and rest pose (in world space, so object transforms count too).
names, new_names = set(arm.data.bones.keys()), set(new_arm.data.bones.keys())
if names != new_names:
    raise SystemExit("bones differ: only in clips %s, only in body %s"
                     % (sorted(names - new_names), sorted(new_names - names)))
worst = 0.0
for b in arm.data.bones:
    a = np.array(arm.matrix_world @ b.matrix_local)
    c = np.array(new_arm.matrix_world @ new_arm.data.bones[b.name].matrix_local)
    worst = max(worst, float(np.abs(a - c).max()))
print("rest pose max difference", round(worst, 6), flush=True)
if worst > REST_TOL:
    raise SystemExit("rest poses differ by %.4f (> %g)" % (worst, REST_TOL))

for o in old:
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
for m in meshes:
    m.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
body = bpy.context.view_layer.objects.active
mw = body.matrix_world.copy()
body.parent = arm
body.matrix_world = mw
mods = [m for m in body.modifiers if m.type == "ARMATURE"]
if not mods:
    mods = [body.modifiers.new("Armature", "ARMATURE")]
for m in mods:
    m.object = arm
for o in others:
    bpy.data.objects.remove(o, do_unlink=True)
print("body", body.name, "verts", len(body.data.vertices), "groups", len(body.vertex_groups), flush=True)
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("SWAP_BODY_OK", OUT, flush=True)
