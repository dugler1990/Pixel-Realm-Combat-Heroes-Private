"""Does the demon's bone point where the source's bone points? Per bone, per frame, in degrees.

    .venv-bpy/Scripts/python.exe dir_check.py <animated.blend> <clip.bvh> <action>

With bind matching the transfer is

    Rd(t) = Rs(t) . Rs(ref)^-1 . Rd(ref)

and Rd(ref) is built so that Rd(ref).y == Rs(ref).y. Substituting, Rd(t).y == Rs(t).y exactly:
**every bone should point exactly where its source counterpart points, on every frame.** That
is a hard invariant, so any bone that is not near zero here is a bug, not a proportion issue -
except the arms, which ARM_ELEV_CAP deliberately pulls down, and those should show up as a
clean positive error only when the source arm is above the cap.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

BLEND, BVH, ACTION = sys.argv[1], sys.argv[2], sys.argv[3]
ROLE = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
R = json.load(open(ROLE))
PAIRS = [
    ("Hips", R["root"]), ("Spine1", R["spine"]), ("Chest", R["chest"]), ("Head", R["neck"]),
    ("LeftShoulder", R["arm_l"]["shoulder"]), ("LeftArm", R["arm_l"]["elbow"]),
    ("LeftForeArm", R["arm_l"]["wrist"]), ("LeftHand", R["arm_l"]["hand"]),
    ("RightShoulder", R["arm_r"]["shoulder"]), ("RightArm", R["arm_r"]["elbow"]),
    ("RightForeArm", R["arm_r"]["wrist"]), ("RightHand", R["arm_r"]["hand"]),
    ("LeftLeg", R["leg_l"]["hip"]), ("LeftShin", R["leg_l"]["knee"]),
    ("LeftFoot", R["leg_l"]["ankle"]), ("LeftToeBase", R["leg_l"]["foot"]),
    ("RightLeg", R["leg_r"]["hip"]), ("RightShin", R["leg_r"]["knee"]),
    ("RightFoot", R["leg_r"]["ankle"]), ("RightToeBase", R["leg_r"]["foot"]),
]

bpy.ops.wm.open_mainfile(filepath=os.path.abspath(BLEND))
tgt = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
sc = bpy.context.scene
ad = tgt.animation_data
act = bpy.data.actions[ACTION]
ad.action = act
if hasattr(act, "slots") and hasattr(ad, "action_slot") and len(act.slots):
    ad.action_slot = act.slots[0]
f0, f1 = int(act.frame_start), int(act.frame_end)
before = set(bpy.data.objects)
bpy.ops.import_anim.bvh(filepath=os.path.abspath(BVH), global_scale=0.01, rotate_mode="NATIVE")
src = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"][0]

Y = Vector((0, 1, 0))
err = {s: [] for s, _ in PAIRS}
elev = {s: [] for s, _ in PAIRS}
for fr in range(f0, f1 + 1, 3):
    sc.frame_set(fr)
    bpy.context.view_layer.update()
    for s, t in PAIRS:
        spb, tpb = src.pose.bones.get(s), tgt.pose.bones.get(t)
        if not spb or not tpb:
            continue
        ds = ((src.matrix_world @ spb.matrix).to_3x3() @ Y).normalized()
        dt = ((tgt.matrix_world @ tpb.matrix).to_3x3() @ Y).normalized()
        err[s].append(math.degrees(ds.angle(dt)))
        elev[s].append(math.degrees(math.asin(max(-1.0, min(1.0, ds.z)))))

print("%-14s %-12s  mean   max   | source elevation range" % ("source bone", "ours"))
for s, t in PAIRS:
    if not err[s]:
        print("%-14s %-12s  (not present)" % (s, t))
        continue
    e = np.array(err[s])
    v = np.array(elev[s])
    flag = "  <-- " if e.mean() > 5 else ""
    print("%-14s %-12s %5.1f %5.1f   | %+5.0f .. %+5.0f%s" % (
        s, t, e.mean(), e.max(), v.min(), v.max(), flag))
