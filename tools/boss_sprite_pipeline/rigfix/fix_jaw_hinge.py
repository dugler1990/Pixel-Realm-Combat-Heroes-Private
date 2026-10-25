"""Drop the jaw hinge to the top of the jaw's own geometry.

The jaw bone pivoted at z 0.207 while the jaw geometry spans z 0.118..0.193 - about 1.4 cm
above the whole jaw. Rotating about a point that floats above the jaw swings it back and up
rather than down and open. Measured effect is modest (jaw_hinge_test.py: worth roughly 5
degrees of rotation at full close) but it is free, and it is what makes -14 read as a proper
shut mouth instead of a clamp.

Only the bone's head moves; length, direction and all weights are untouched.

Writes rigged_jaw_hinge.glb and sets jaw_closed_deg.
"""
import json
import os
import sys

import bpy
from mathutils import Vector

RIG = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\rigged_jaw_smoothw.glb"
ROLES = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
OUT = os.path.dirname(RIG)
NEW_Z = float(sys.argv[1]) if len(sys.argv) > 1 else 0.193
CLOSED = float(sys.argv[2]) if len(sys.argv) > 2 else 14.0

R = json.load(open(ROLES))
jaw = R["jaw"]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=RIG)
for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
    for o in list(coll.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(coll)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]

bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
eb = arm.data.edit_bones[jaw]
eb.use_connect = False
was = (arm.matrix_world @ eb.head).z
d = eb.tail - eb.head
eb.head = Vector((eb.head.x, eb.head.y, NEW_Z))
eb.tail = eb.head + d
bpy.ops.object.mode_set(mode="OBJECT")
print("jaw hinge z %.3f -> %.3f" % (was, (arm.matrix_world @ arm.data.bones[jaw].head_local).z),
      flush=True)

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
out = os.path.join(OUT, "rigged_jaw_hinge.glb")
bpy.ops.export_scene.gltf(filepath=out, use_selection=True)
print("EXPORTED", out, flush=True)

R["jaw_closed_deg"] = CLOSED
R["_anatomy"]["jaw"] = ("jaw, child of bone_34 (the snout). Hinge lowered to z %.3f - it sat at "
                        "0.207, above the jaw's own span of 0.118..0.193. Negative closes; "
                        "%.0f is the chosen shut pose (JAW_HINGE4.png)." % (NEW_Z, CLOSED))
json.dump(R, open(ROLES, "w"), indent=1)
print("jaw_closed_deg ->", CLOSED, flush=True)
