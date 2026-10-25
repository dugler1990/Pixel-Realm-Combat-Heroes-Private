"""Re-parent the wing bones from the neck (bone_13) to the chest (bone_12).

add_wing_bones.py parented them to bone_13 without checking what bone_13 was; the verification
pass showed it is the NECK, so every head turn dragged both wings. Wings belong on the chest.
"""
import bpy, json, os
RIG=r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\rigged_jaw.glb"
ROLES=r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
OUT=os.path.dirname(RIG)
roles=json.load(open(ROLES)); chest=roles["chest"]
bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=RIG)
for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
    for o in list(coll.objects): bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(coll)
arm=[o for o in bpy.data.objects if o.type=='ARMATURE'][0]; mesh=[o for o in bpy.data.objects if o.type=='MESH'][0]
bpy.context.view_layer.objects.active=arm; bpy.ops.object.mode_set(mode='EDIT')
eb=arm.data.edit_bones
for w in ("wing_L_a","wing_R_a"):
    if w in eb:
        print("was:", w, "->", eb[w].parent.name if eb[w].parent else None, flush=True)
        eb[w].parent = eb[chest]; eb[w].use_connect=False
        print("now:", w, "->", eb[w].parent.name, flush=True)
bpy.ops.object.mode_set(mode='OBJECT')
for img in bpy.data.images:
    if img.users and not img.packed_file:
        try: img.pack()
        except RuntimeError: pass
bpy.ops.object.select_all(action='DESELECT'); mesh.select_set(True); arm.select_set(True)
bpy.context.view_layer.objects.active=arm
out=os.path.join(OUT,"rigged_jaw_wingfix.glb")
bpy.ops.export_scene.gltf(filepath=out, use_selection=True)
print("EXPORTED", out)
