"""Export the gargoyle's actions to BVH so the real retargeter can consume them.

    .venv-bpy/Scripts/python.exe gargoyle_to_bvh.py <source.glb> <out_dir> [limit]

gargoyle_map.py was a parallel, minimal reimplementation of the transfer and it skipped every
correction retarget_bvh.py has: the arm elevation cap (his armpit is fused, so a full raise
tears), the jaw pin, the euler-wrap rejection, the clavicle handling. The result tumbled and
splayed.

Exporting to BVH instead means the gargoyle goes through the same pipeline as everything else,
and inherits all of it. The only thing that changes is the bone-name table.
"""
import glob
import os
import sys

import bpy

SRC, OUT = (os.path.abspath(p) for p in sys.argv[1:3])
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 12
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
sc = bpy.context.scene
ad = arm.animation_data

bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
bpy.context.view_layer.objects.active = arm

n = 0
for act in sorted(bpy.data.actions, key=lambda a: a.name):
    short = act.name.split("|")[-1]
    # one creature variant is enough; the other is the same motion on the same rig
    if "Daedalus" not in short:
        continue
    f0, f1 = (int(round(x)) for x in act.frame_range)
    if f1 - f0 < 8:                       # single-frame poses like Dead are not animation
        continue
    ad.action = act
    if hasattr(act, "slots") and hasattr(ad, "action_slot") and len(act.slots):
        ad.action_slot = act.slots[0]
    sc.frame_start, sc.frame_end = f0, f1
    name = short.replace("F_Daedalus_", "gar_").split("_F_")[0]
    path = os.path.join(OUT, name + ".bvh")
    bpy.ops.export_anim.bvh(filepath=path, frame_start=f0, frame_end=f1,
                            root_transform_only=False)
    print("exported %-22s %4d frames -> %s" % (name, f1 - f0 + 1, os.path.basename(path)),
          flush=True)
    n += 1
    if n >= LIMIT:
        break
print("GARGOYLE_BVH_OK", n, "clips ->", OUT, flush=True)
