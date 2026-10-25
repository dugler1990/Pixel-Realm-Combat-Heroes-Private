"""Draw the source skeleton and the retargeted demon skeleton in the same frame, same scale.

    .venv-bpy/Scripts/python.exe pose_compare.py <animated.blend> <clip.bvh> <action> <out.png>

Corresponding bones get the same colour. If bind matching works, frame 1 of the two should sit
on top of each other; where they diverge is the error, and by how much is the size of it.
Both are normalised to the same height and their hips put at the origin, so only pose differs.
"""
import math
import os
import sys

import bpy
import numpy as np
from PIL import Image, ImageDraw

BLEND, BVH, ACTION, OUT = sys.argv[1], sys.argv[2], sys.argv[3], os.path.abspath(sys.argv[4])
ROLE = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
import json
R = json.load(open(ROLE))
PX = 560

PAIRS = [                                  # (source bone, our bone, colour)
    ("Hips", R["root"], (255, 255, 255)),
    ("Spine1", R["spine"], (200, 200, 200)),
    ("Chest", R["chest"], (150, 200, 255)),
    ("Head", R["neck"], (255, 80, 255)),
    ("LeftShoulder", R["arm_l"]["shoulder"], (255, 170, 60)),
    ("LeftArm", R["arm_l"]["elbow"], (255, 90, 60)),
    ("LeftForeArm", R["arm_l"]["wrist"], (255, 40, 40)),
    ("LeftHand", R["arm_l"]["hand"], (200, 20, 20)),
    ("RightShoulder", R["arm_r"]["shoulder"], (120, 255, 120)),
    ("RightArm", R["arm_r"]["elbow"], (60, 220, 60)),
    ("RightForeArm", R["arm_r"]["wrist"], (30, 180, 30)),
    ("RightHand", R["arm_r"]["hand"], (20, 130, 20)),
    ("LeftLeg", R["leg_l"]["hip"], (255, 255, 90)),
    ("LeftShin", R["leg_l"]["knee"], (220, 220, 50)),
    ("LeftFoot", R["leg_l"]["ankle"], (180, 180, 30)),
    ("RightLeg", R["leg_r"]["hip"], (90, 200, 255)),
    ("RightShin", R["leg_r"]["knee"], (50, 160, 230)),
    ("RightFoot", R["leg_r"]["ankle"], (30, 120, 200)),
]


def segments(arm, names, frame, sc):
    sc.frame_set(frame)
    bpy.context.view_layer.update()
    out = {}
    for n in names:
        pb = arm.pose.bones.get(n)
        if pb:
            out[n] = (arm.matrix_world @ pb.head, arm.matrix_world @ pb.tail)
    return out


def normalise(seg, pts):
    """hips to the origin, scale so the figure is 1.0 tall"""
    P = np.array([list(v) for hw in seg.values() for v in hw])
    h = P[:, 2].max() - P[:, 2].min()
    o = np.array(list(seg[pts][0]))
    return {k: ((np.array(list(a)) - o) / h, (np.array(list(b)) - o) / h) for k, (a, b) in seg.items()}


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

FRAMES = [f0, f0 + (f1 - f0) // 3, f0 + 2 * (f1 - f0) // 3]
sheet = Image.new("RGB", (PX * len(FRAMES), PX * 2), (22, 22, 26))
d = ImageDraw.Draw(sheet)

for col, fr in enumerate(FRAMES):
    s = normalise(segments(src, [p[0] for p in PAIRS], fr, sc), "Hips")
    t = normalise(segments(tgt, [p[1] for p in PAIRS], fr, sc), R["root"])
    for row, (yaw, tag) in enumerate(((0, "front"), (90, "side"))):
        ox, oy = col * PX, row * PX
        c, sn = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))

        def put(v):
            x = v[0] * c - v[1] * sn
            return (ox + PX * 0.5 + x * PX * 0.42, oy + PX * 0.78 - v[2] * PX * 0.42)

        for sname, tname, colour in PAIRS:
            if sname in s:
                a, b = s[sname]
                d.line([put(a), put(b)], fill=colour, width=5)
            if tname in t:
                a, b = t[tname]
                d.line([put(a), put(b)], fill=colour, width=2)
                d.ellipse([put(a)[0] - 3, put(a)[1] - 3, put(a)[0] + 3, put(a)[1] + 3], fill=(0, 0, 0))
        lab = "f%d %s  thick = source, thin = demon" % (fr, tag)
        d.text((ox + 9, oy + 9), lab, fill=(0, 0, 0))
        d.text((ox + 8, oy + 8), lab, fill=(255, 230, 80))

        # how far apart are they, as a fraction of height?
        err = []
        for sname, tname, _ in PAIRS:
            if sname in s and tname in t:
                err.append(np.linalg.norm(s[sname][0] - t[tname][0]))
        m = "mean joint offset %.3f  max %.3f" % (np.mean(err), np.max(err))
        d.text((ox + 9, oy + PX - 21), m, fill=(0, 0, 0))
        d.text((ox + 8, oy + PX - 22), m, fill=(150, 230, 150))
        if row == 0:
            print("f%-4d %s" % (fr, m), flush=True)

sheet.save(OUT)
print("POSE_COMPARE", OUT, flush=True)
