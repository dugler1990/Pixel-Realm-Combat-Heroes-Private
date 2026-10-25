"""Kimodo G1-robot .npz -> BVH, so the normal retargeter can consume robot-mode output.

    python g1_to_bvh.py <motion.npz> <out.bvh>

The demo's robot mode writes a 34-joint G1 skeleton (`global_rot_mats (F,34,3,3)`), not SOMA's
77. Nothing in the demon pipeline speaks that, so this writes it out as a BVH with the G1's own
joint names; `retarget_bvh.py` then runs against it with SOURCE=g1 exactly as it does for the
gargoyle, using MAP_G1 instead of MAP.

Skeleton constants come from `g1_skel.json`, dumped from `kimodo.skeleton.G1Skeleton34` rather
than typed out, so names, parents and rest offsets cannot drift from the model's own definition.

**What the G1 does not have**: a head, a neck, or clavicles. Its 34 joints are two legs, a
three-segment waist and two arms. Those bones on the demon stay at rest whatever the map says.

**Its joints are single-axis.** A hip is three joints (`left_hip_pitch/roll/yaw`), so the full
hip rotation only exists at the *last* of the three; mapping the first gives you a third of the
motion. MAP_G1 therefore targets the yaw/last joint of each chain.
"""
import json
import os
import sys

import numpy as np

SRC, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
SKEL = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "g1_skel.json")))
NAMES, PARENTS = SKEL["names"], SKEL["parents"]
NEUTRAL = np.asarray(SKEL["neutral"], dtype=np.float64)
FPS = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0

d = np.load(SRC, allow_pickle=True)
local = np.asarray(d["local_rot_mats"], dtype=np.float64)        # (F, 34, 3, 3)
root = np.asarray(d["root_positions"], dtype=np.float64)         # (F, 3)
F = local.shape[0]
assert local.shape[1] == len(NAMES), "expected %d joints, got %d" % (len(NAMES), local.shape[1])

# BVH is written in centimetres; the rest of the pipeline divides by 100 on import
offsets = np.zeros_like(NEUTRAL)
for j, p in enumerate(PARENTS):
    offsets[j] = NEUTRAL[j] if p < 0 else NEUTRAL[j] - NEUTRAL[p]
offsets *= 100.0


def euler_zyx(m):
    """BVH's Zrotation Yrotation Xrotation order, in degrees."""
    sy = -m[2, 0]
    sy = max(-1.0, min(1.0, sy))
    y = np.arcsin(sy)
    if abs(sy) < 0.999999:
        x = np.arctan2(m[2, 1], m[2, 2])
        z = np.arctan2(m[1, 0], m[0, 0])
    else:                                  # gimbal lock: fold the spin into Z
        x = np.arctan2(-m[1, 2], m[1, 1])
        z = 0.0
    return np.degrees([z, y, x])


lines, order = [], []


def emit(j, depth):
    pad = "  " * depth
    kids = [k for k, p in enumerate(PARENTS) if p == j]
    lines.append("%s%s %s" % (pad, "ROOT" if PARENTS[j] < 0 else "JOINT", NAMES[j]))
    lines.append(pad + "{")
    lines.append("%s  OFFSET %.6f %.6f %.6f" % (pad, *offsets[j]))
    if PARENTS[j] < 0:
        lines.append(pad + "  CHANNELS 6 Xposition Yposition Zposition "
                           "Zrotation Yrotation Xrotation")
    else:
        lines.append(pad + "  CHANNELS 3 Zrotation Yrotation Xrotation")
    order.append(j)
    for k in kids:
        emit(k, depth + 1)
    if not kids:                            # BVH requires a terminating End Site
        lines.append(pad + "  End Site")
        lines.append(pad + "  {")
        lines.append(pad + "    OFFSET 0.000000 5.000000 0.000000")
        lines.append(pad + "  }")
    lines.append(pad + "}")


lines.append("HIERARCHY")
emit(SKEL["root_idx"], 0)
lines.append("MOTION")
lines.append("Frames: %d" % F)
lines.append("Frame Time: %.9f" % (1.0 / FPS))

for f in range(F):
    vals = []
    for j in order:
        if PARENTS[j] < 0:
            vals += ["%.6f" % v for v in (root[f] * 100.0)]
        vals += ["%.6f" % v for v in euler_zyx(local[f, j])]
    lines.append(" ".join(vals))

os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
open(OUT, "w").write("\n".join(lines) + "\n")
print("WROTE %s  %d frames  %d joints" % (OUT, F, len(NAMES)), flush=True)
