"""Layer wing and tail motion onto already-baked actions.

    .venv-bpy/Scripts/python.exe wing_overlay.py <animated.blend> <out.blend> [strength]

Kimodo's skeleton has no wings and no tail, so those bones sit at rest in every clip retargeted
from it - which is the single biggest thing making the clips read as stiff, more than any
retargeting error. The gargoyle source does animate them, but that only covers its own 42 clips.

Rather than invent a flap, the overlay is *driven by the body*: wings and tail react to what the
torso is already doing, so a violent clip gets a violent wing reaction and an idle gets a slow
settle, with no per-clip tuning.

  drive  = how fast the chest is rotating this frame, normalised over the clip
  flap   = a slow breathing cycle, always present, small
  react  = drive, which flares the wings open and swings the tail back

Existing wing/tail keys are replaced; every other bone is untouched.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Quaternion, Vector

BLEND, OUT = (os.path.abspath(p) for p in sys.argv[1:3])
STRENGTH = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
ROLE = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
R = json.load(open(ROLE))

WING = [(R["wing_l"]["arm"], 1.0), (R["wing_l"]["fan"], 1.0),
        (R["wing_r"]["arm"], -1.0), (R["wing_r"]["fan"], -1.0)]
TAIL = list(R.get("tail", []))
CHEST = R["chest"]

FLAP_HZ = 0.55          # slow breathing cycle
FLAP_DEG = 4.0          # amplitude of that cycle
REACT_DEG = 26.0        # how far the wings flare on a violent frame
TAIL_DEG = 18.0

bpy.ops.wm.open_mainfile(filepath=BLEND)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
sc = bpy.context.scene
ad = arm.animation_data
tw = arm.matrix_world
Y = Vector((0, 1, 0))

present = [(n, s) for n, s in WING if n in arm.pose.bones]
tails = [n for n in TAIL if n in arm.pose.bones]
print("wing bones:", [n for n, _ in present], "tail:", tails, flush=True)
if not present:
    print("NO_WING_BONES - nothing to do", flush=True)
    sys.exit(0)

for act in sorted(bpy.data.actions, key=lambda a: a.name):
    ad.action = act
    if hasattr(act, "slots") and hasattr(ad, "action_slot") and len(act.slots):
        ad.action_slot = act.slots[0]
    f0, f1 = int(act.frame_start), int(act.frame_end)
    if f1 <= f0:
        continue

    # how hard is the body working, per frame
    drive, prev = [], None
    for fr in range(f0, f1 + 1):
        sc.frame_set(fr)
        bpy.context.view_layer.update()
        d = ((tw @ arm.pose.bones[CHEST].matrix).to_3x3().normalized() @ Y).normalized()
        drive.append(0.0 if prev is None else math.degrees(prev.angle(d)))
        prev = d
    peak = max(drive) or 1.0
    drive = [d / peak for d in drive]
    # let a reaction persist rather than blink for one frame
    for i in range(1, len(drive)):
        drive[i] = max(drive[i], drive[i - 1] * 0.88)

    for i, fr in enumerate(range(f0, f1 + 1)):
        sc.frame_set(fr)
        t = (fr - f0) / 24.0
        flap = math.sin(2 * math.pi * FLAP_HZ * t)
        for name, side in present:
            pb = arm.pose.bones[name]
            pb.rotation_mode = "QUATERNION"
            # rotate about the bone's own local X: opening and closing, not twisting
            ang = math.radians(STRENGTH * (FLAP_DEG * flap + REACT_DEG * drive[i]))
            pb.rotation_quaternion = Quaternion(Vector((1.0, 0.0, 0.0)), ang * side)
            pb.keyframe_insert("rotation_quaternion", frame=fr)
        for k, name in enumerate(tails):
            pb = arm.pose.bones[name]
            pb.rotation_mode = "QUATERNION"
            lag = drive[max(i - 2 * (k + 1), 0)]          # the tail follows late
            ang = math.radians(STRENGTH * (TAIL_DEG * lag + 3.0 * flap))
            pb.rotation_quaternion = Quaternion(Vector((1.0, 0.0, 0.0)), ang)
            pb.keyframe_insert("rotation_quaternion", frame=fr)
    print("overlaid", act.name, f1 - f0 + 1, "frames, peak body motion %.1f deg/frame" % peak,
          flush=True)

ad.action = None
for img in bpy.data.images:
    if img.users and not img.packed_file:
        try:
            img.pack()
        except RuntimeError:
            pass
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("WING_OVERLAY_OK", OUT, flush=True)
