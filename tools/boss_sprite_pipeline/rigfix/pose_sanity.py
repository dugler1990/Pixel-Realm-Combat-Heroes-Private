"""Is the retarget crumpling the character, or is the source motion itself folded?

    .venv-bpy/Scripts/python.exe pose_sanity.py <animated.blend> <bvh_dir> [action]

Three metrics were tried before this one and two were useless, which is worth recording so they
are not tried again:

  torso tilt from vertical     blind - a figure with its arms twisted backwards and its elbows
                               inverted still stands upright. Only caught "fell over".
  bounding-box aspect          same blindness, for the same reason.
  mean joint offset            real, and already in pose_compare.py, but it measures the demon
                               against the source. When the SOURCE is folded the demon is
                               faithfully folded too and the number stays low.

What actually separates "the mapping crumpled him" from "the clip is just a fold" is
**compression relative to the source**:

  spine = |hips -> head| / its own rest length, measured on each skeleton separately
  slack = spine(source) - spine(demon)

Both bend together on a real crouch or dive, so slack stays near zero whatever the pose. Only a
bad bind compresses the demon further than its source, and that shows up as positive slack. The
threshold below (0.12) was set from measured runs, not guessed - see the table this prints.
"""
import glob
import json
import math
import os
import sys

import bpy
from mathutils import Vector

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
BLEND = os.path.abspath(ARGV[0])
BVH_DIR = os.path.abspath(ARGV[1])
ONLY = ARGV[2] if len(ARGV) > 2 else None
SLACK_BAD = 0.12

bpy.ops.wm.open_mainfile(filepath=BLEND)
tgt = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
if tgt.animation_data is None:
    tgt.animation_data_create()
for tr in tgt.animation_data.nla_tracks:
    tr.mute = True

names = [b.name for b in tgt.data.bones]
T_LO = "bone_0" if "bone_0" in names else names[0]
T_HI = "bone_13" if "bone_13" in names else names[-1]


def span(arm, lo, hi):
    return ((arm.matrix_world @ arm.pose.bones[lo].head)
            - (arm.matrix_world @ arm.pose.bones[hi].head)).length


def rest_span(arm, lo, hi):
    return ((arm.matrix_world @ arm.data.bones[lo].head_local)
            - (arm.matrix_world @ arm.data.bones[hi].head_local)).length


print("%-20s %7s %7s %7s  %s" % ("clip", "demon", "source", "slack", "verdict"), flush=True)
bad = 0
done = 0
for act in sorted(bpy.data.actions, key=lambda a: a.name):
    if ONLY and act.name != ONLY:
        continue
    bvh = os.path.join(BVH_DIR, act.name + ".bvh")
    if not os.path.exists(bvh):
        hit = glob.glob(os.path.join(BVH_DIR, "*.bvh"))
        bvh = hit[0] if len(hit) == 1 else None
    if not bvh:
        print("%-20s   no matching bvh, skipped" % act.name[:20], flush=True)
        continue

    before = set(bpy.data.objects)
    bpy.ops.import_anim.bvh(filepath=bvh, global_scale=0.01, rotate_mode="NATIVE")
    src = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"][0]
    sb = [b.name for b in src.data.bones]
    s_lo = next((n for n in ("Hips", "pelvis_skel", "Bip01-Pelvis_03") if n in sb), sb[0])
    s_hi = next((n for n in ("Head", "Chest", "Bip01-Head_09", "waist_pitch_skel")
                 if n in sb), sb[-1])

    tgt.animation_data.action = act
    f0, f1 = (int(round(x)) for x in act.frame_range)
    t_rest, s_rest = rest_span(tgt, T_LO, T_HI), rest_span(src, s_lo, s_hi)
    d_ratio, s_ratio = [], []
    for f in range(f0, f1 + 1, max((f1 - f0) // 12, 1)):
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        if t_rest > 1e-6:
            d_ratio.append(span(tgt, T_LO, T_HI) / t_rest)
        if s_rest > 1e-6:
            s_ratio.append(span(src, s_lo, s_hi) / s_rest)
    bpy.data.objects.remove(src, do_unlink=True)

    med = lambda v: sorted(v)[len(v) // 2] if v else float("nan")
    d, s = med(d_ratio), med(s_ratio)
    slack = s - d
    verdict = "CRUMPLED - demon folds %.0f%% more than source" % (slack * 100) \
        if slack > SLACK_BAD else "ok"
    bad += slack > SLACK_BAD
    done += 1
    print("%-20s %7.2f %7.2f %7.2f  %s" % (act.name[:20], d, s, slack, verdict), flush=True)

print("\nSANITY %d bad of %d  (slack > %.2f)" % (bad, done, SLACK_BAD), flush=True)
