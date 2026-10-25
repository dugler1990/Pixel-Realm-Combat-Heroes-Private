"""What is in a rigged GLB: bones, wing bones, and whether the animation actually moves them.

    .venv-bpy/Scripts/python.exe probe_rig.py <dir-of-glb>

The question for a candidate motion source is not "does it have wings" but "does its animation
move them" - a wing bone that never rotates is no more use to us than Kimodo's missing one.
"""
import glob, math, os, sys
import bpy
from mathutils import Vector

for path in sorted(glob.glob(os.path.join(os.path.abspath(sys.argv[1]), "*.glb"))):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    try:
        bpy.ops.import_scene.gltf(filepath=path)
    except Exception as e:
        print("%-44s IMPORT FAIL %s" % (os.path.basename(path)[:44], type(e).__name__))
        continue
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not arms:
        print("%-44s no armature" % os.path.basename(path)[:44])
        continue
    arm = arms[0]
    names = [b.name for b in arm.data.bones]
    wing = [n for n in names if any(w in n.lower() for w in ("wing", "ala", "flap", "feather"))]
    acts = list(bpy.data.actions)
    sc = bpy.context.scene
    moved = set()
    span = 0.0
    if acts:
        ad = arm.animation_data
        a = acts[0]
        if ad:
            ad.action = a
            if hasattr(a, "slots") and hasattr(ad, "action_slot") and len(a.slots):
                ad.action_slot = a.slots[0]
            f0, f1 = (int(round(x)) for x in a.frame_range)
            ref = {}
            for fr in (f0, (f0 + f1) // 2, f1):
                sc.frame_set(fr)
                bpy.context.view_layer.update()
                for pb in arm.pose.bones:
                    d = (arm.matrix_world @ pb.matrix).to_3x3().normalized() @ Vector((0, 1, 0))
                    if pb.name in ref:
                        ang = math.degrees(ref[pb.name].angle(d.normalized()))
                        if ang > 5:
                            moved.add(pb.name)
                        span = max(span, ang)
                    else:
                        ref[pb.name] = d.normalized()
    wm = [n for n in wing if n in moved]
    print("%-40s bones %3d  actions %2d  wing-bones %2d  moved %3d  WING MOVED %2d  max %5.1f deg"
          % (os.path.basename(path)[:40], len(names), len(acts), len(wing), len(moved), len(wm), span))
    if wing:
        print("      wing bones: %s" % ", ".join(wing[:6]))
