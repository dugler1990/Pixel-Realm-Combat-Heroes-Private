"""How far apart are his hands through a clip? (Can a two-handed weapon ride on the clip as it is.)

    .venv-bpy/Scripts/python.exe tools/boss_sprite_pipeline/_checks/hand_gap.py <animated.blend> <roles.json> [action ...]

For each action (default: all): per frame, the palm points (40 % along each hand bone) in world space, their distance
as a share of his height (his rest-pose mesh height). Prints HAND_GAP {action: {min, median, max, spread, frames}}:
a two-handed grip holds when the gap is small (hands about a fist apart on the hilt: roughly 0.05-0.10 of height)
and steady (spread = max - min small); a large or swinging gap means the off hand needs IK.
"""
import json
import sys

import bpy
import numpy as np

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
BLEND, ROLES, ONLY = ARGS[0], ARGS[1], ARGS[2:]
bpy.ops.wm.open_mainfile(filepath=BLEND)
roles = json.load(open(ROLES))
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
V = np.array([(body.matrix_world @ v.co)[:] for v in list(body.data.vertices)[::50]])
height = float(np.ptp(V[:, 2]))
names = {s: roles[f"arm_{s}"]["hand"] for s in ("l", "r")}
sc = bpy.context.scene
res = {}
for act in bpy.data.actions:
    if ONLY and act.name not in ONLY:
        continue
    arm.animation_data_create()
    arm.animation_data.action = act
    lo, hi = (int(round(x)) for x in act.frame_range)
    gaps = []
    for f in range(lo, hi + 1):
        sc.frame_set(f)
        M = arm.matrix_world
        palm = {}
        for s, b in names.items():
            pb = arm.pose.bones[b]
            palm[s] = np.array((M @ (pb.head + (pb.tail - pb.head) * 0.4))[:])
        gaps.append(float(np.linalg.norm(palm["l"] - palm["r"])) / height)
    g = np.array(gaps)
    res[act.name] = {"min": round(float(g.min()), 3), "median": round(float(np.median(g)), 3),
                     "max": round(float(g.max()), 3), "spread": round(float(g.max() - g.min()), 3),
                     "frames": len(g)}
print("HAND_GAP " + json.dumps(res))
