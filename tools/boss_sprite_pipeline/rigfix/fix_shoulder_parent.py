"""Re-parent the clavicles (bone_14 / bone_24) from bone_13 to the chest (bone_12).

Same class of bug as the wings (fix_wing_parent.py): UniRig hung them off bone_13, and the
skeleton dump shows bone_13 is not a neck at all - it owns 56k of vertex weight centred at
z 0.227, i.e. **the whole head**. So every head turn drags both shoulders. Clavicles belong
on the chest.

Also writes the measured anatomy into bone_roles.json as `_anatomy`, because the role *names*
in that file are off by one on the arms: bone_14 is the clavicle, not the shoulder joint.
Renaming the keys would break animate_procedural.py, so the truth is recorded beside them.
"""
import json
import os

import bpy

RIG = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\rigged_jaw_wingfix.glb"
ROLES = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
OUT = os.path.dirname(RIG)

roles = json.load(open(ROLES))
chest = roles["chest"]
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
eb = arm.data.edit_bones
for c in (roles["arm_l"]["shoulder"], roles["arm_r"]["shoulder"]):
    print("was:", c, "->", eb[c].parent.name if eb[c].parent else None, flush=True)
    eb[c].parent = eb[chest]
    eb[c].use_connect = False
    print("now:", c, "->", eb[c].parent.name, flush=True)
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
out = os.path.join(OUT, "rigged_jaw_shoulderfix.glb")
bpy.ops.export_scene.gltf(filepath=out, use_selection=True)
print("EXPORTED", out, flush=True)

roles["_anatomy"] = {
    "note": ("Measured from the skeleton + vertex weights (scratchpad/skel_dump.py), 2026-09-24. "
             "The role NAMES above are off by one on the arms and wrong for the head; these are "
             "the real bones. Kept separate because animate_procedural.py uses the old names."),
    "bone_1": "whole torso (52k weight, z 0.058) - drive from Spine1",
    "bone_12": "chest, spans waist to shoulders (2k weight) - drive from Chest",
    "bone_13": "THE HEAD, not a neck (56k weight, z 0.227) - drive from Head",
    "bone_34": "snout/muzzle, 3.6 cm, points forward out of the face - leave at rest",
    "jaw": "jaw, child of bone_34; negative angle closes, ~-20 shuts, -30 over-closes",
    "bone_14/bone_24": "clavicle (18k/16k weight on the upper chest) - drive from LeftShoulder",
    "bone_15/bone_25": "upper arm - drive from LeftArm",
    "bone_16/bone_26": "forearm - drive from LeftForeArm",
    "bone_17/bone_27": "hand - drive from LeftHand",
    "bone_2/3/4": "thigh / shin / foot - these were already right",
}
json.dump(roles, open(ROLES, "w"), indent=1)
print("ROLES_ANNOTATED", flush=True)
