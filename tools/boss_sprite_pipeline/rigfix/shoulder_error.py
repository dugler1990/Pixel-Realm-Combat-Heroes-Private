"""Measure what happens to the demon's shoulder girdle during each clip.

    .venv-bpy/Scripts/python.exe shoulder_error.py <animated.blend> <bvh_dir>

Some clips look like his arm collapses into his body and others look fine, so the question is
which clips and by how much - not "should we damp the clavicles". Damping everything on a
hunch would change every clip including the ones that already work.

Per clip, per frame:
  width   - distance between his two upper-arm roots, as a fraction of its own rest value.
            Below 1.0 means his shoulder girdle is narrower than sculpted.
  src     - the same ratio on the source skeleton, for comparison. If the source narrows by
            the same fraction, the transfer is faithful and the look is the motion's fault.
  tuck    - how close the elbow comes to the torso midline, as a fraction of shoulder width.
            This is what reads as "collapsing into his body".
"""
import glob
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

BLEND, BVH_DIR = (os.path.abspath(p) for p in sys.argv[1:3])
ROLE = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
R = json.load(open(ROLE))
UPL, UPR = R["arm_l"]["elbow"], R["arm_r"]["elbow"]        # names are off by one: upper arms
FOL, FOR = R["arm_l"]["wrist"], R["arm_r"]["wrist"]        # forearms

bpy.ops.wm.open_mainfile(filepath=BLEND)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
sc = bpy.context.scene
ad = arm.animation_data
tw = arm.matrix_world

rest_w = (tw @ arm.data.bones[UPL].head_local - tw @ arm.data.bones[UPR].head_local).length
print("rest shoulder width %.4f" % rest_w, flush=True)
print("%-16s %7s %7s %7s %7s  %s" % ("clip", "minW", "meanW", "srcMinW", "minTuck", "verdict"),
      flush=True)

for bvh in sorted(glob.glob(os.path.join(BVH_DIR, "*.bvh"))):
    clip = os.path.splitext(os.path.basename(bvh))[0]
    if clip not in bpy.data.actions:
        continue
    act = bpy.data.actions[clip]
    ad.action = act
    if hasattr(act, "slots") and hasattr(ad, "action_slot") and len(act.slots):
        ad.action_slot = act.slots[0]
    before = set(bpy.data.objects)
    bpy.ops.import_anim.bvh(filepath=bvh, global_scale=0.01, rotate_mode="NATIVE")
    src = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"][0]
    sw_rest = None
    ws, sws, tucks = [], [], []
    f0, f1 = int(act.frame_start), int(act.frame_end)
    for fr in range(f0, f1 + 1, 2):
        sc.frame_set(fr)
        bpy.context.view_layer.update()
        L = tw @ arm.pose.bones[UPL].head
        Rt = tw @ arm.pose.bones[UPR].head
        ws.append((L - Rt).length / rest_w)
        mid = (L + Rt) * 0.5
        for fo in (FOL, FOR):
            e = tw @ arm.pose.bones[fo].head
            tucks.append(abs(e.x - mid.x) / max(rest_w, 1e-6))
        if "LeftArm" in src.pose.bones and "RightArm" in src.pose.bones:
            sl = src.matrix_world @ src.pose.bones["LeftArm"].head
            sr = src.matrix_world @ src.pose.bones["RightArm"].head
            d = (sl - sr).length
            if sw_rest is None:
                sw_rest = d
            sws.append(d / max(sw_rest, 1e-9))
    bpy.data.objects.remove(src, do_unlink=True)
    for a2 in list(bpy.data.actions):
        if a2.name.endswith("__src"):
            bpy.data.actions.remove(a2)
    w = np.array(ws)
    s = np.array(sws) if sws else np.array([1.0])
    tk = np.array(tucks)
    # his girdle narrowing much more than the source's is ours; both narrowing is the motion
    verdict = ("OURS" if w.min() < 0.85 and w.min() < s.min() - 0.08 else
               "source" if s.min() < 0.9 else "ok")
    print("%-16s %7.2f %7.2f %7.2f %7.2f  %s" % (
        clip, w.min(), w.mean(), s.min(), tk.min(), verdict), flush=True)
