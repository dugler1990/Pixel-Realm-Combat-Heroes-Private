"""Turn retargeted clips into the three a mesh player needs: idle, move, attack.

    .venv-bpy/Scripts/python.exe player_clips.py <animated.blend> <out.blend>
        [--idle settle_01] [--move jokesillyrun] [--attack overheadchop] [--attack-frames 45-60,108-138]

The input is a retarget_bvh.py output (one action per clip). Writes <out.blend> with exactly the actions
idle, move, attack (the names MeshBoss resolves) and <out>.json with what was done.

idle    the idle clip as is
move    one stride cycle of the locomotion clip: the window (start, length) whose last pose best
        matches its first, the root's horizontal travel removed (the game moves him; the clip
        steps in place). travel_per_frame (model units) is recorded so the player can phase
        the cycle on distance walked, like the sprite walk.
attack  the attack clip cut to --attack-frames: inclusive source frame ranges, spliced in order
        (overheadchop: the arm going up, then the chop; the long hold between is dropped)
"""
import json
import os
import sys

import bpy
import numpy as np

ARGS = sys.argv[1:]


def opt(name, default):
    if name in ARGS:
        i = ARGS.index(name)
        val = ARGS[i + 1]
        del ARGS[i:i + 2]
        return val
    return default


IDLE = opt("--idle", "settle_01")
MOVE = opt("--move", "jokesillyrun")
ATTACK = opt("--attack", "overheadchop")
ATTACK_FRAMES = [[int(v) for v in r.split("-")] for r in opt("--attack-frames", "45-60,108-138").split(",")]
SRC, OUT = (os.path.abspath(a) for a in ARGS[:2])
CYCLE_MIN, CYCLE_MAX = 12, 48      # frames
ROOT = "bone_0"

bpy.ops.wm.open_mainfile(filepath=SRC)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for o in bpy.data.objects:                       # analysis needs bones only: skip the 700k-vert mesh
    if o.type == "MESH":
        for m in o.modifiers:
            m.show_viewport = False
ad = arm.animation_data or arm.animation_data_create()
for t in list(ad.nla_tracks):
    ad.nla_tracks.remove(t)
scene = bpy.context.scene


def use(action):
    ad.action = action
    if hasattr(ad, "action_slot") and len(getattr(action, "slots", ())):
        ad.action_slot = action.slots[0]


def bone_heads(action):
    """[frames, bones, 3] armature-space bone heads, relative to the root head (pose shape only)."""
    use(action)
    f0, f1 = (int(round(v)) for v in action.frame_range)
    out = []
    for f in range(f0, f1 + 1):
        scene.frame_set(f)
        H = np.array([list(pb.head) for pb in arm.pose.bones])
        out.append(H - H[0])
    return np.array(out), f0


def root_world(action):
    use(action)
    f0, f1 = (int(round(v)) for v in action.frame_range)
    pts = []
    for f in range(f0, f1 + 1):
        scene.frame_set(f)
        pts.append(list(arm.matrix_world @ arm.pose.bones[ROOT].head))
    return np.array(pts)


def trim(action, first, last):
    """Keep source frames first..last, shifted to start at frame 1."""
    for fc in action.fcurves:
        kps = fc.keyframe_points
        for i in reversed(range(len(kps))):
            if not (first - 1e-3 <= kps[i].co[0] <= last + 1e-3):
                kps.remove(kps[i])
        for kp in kps:
            kp.co[0] -= first - 1
            kp.handle_left[0] -= first - 1
            kp.handle_right[0] -= first - 1
        fc.update()
    action.use_frame_range = True
    action.frame_start, action.frame_end = 1, last - first + 1


def splice(action, ranges):
    """Source frame ranges, in order, resampled one key per frame from frame 1."""
    frames = [f for a, b in ranges for f in range(a, b + 1)]
    for fc in action.fcurves:
        vals = [fc.evaluate(f) for f in frames]
        fc.keyframe_points.clear()
        fc.keyframe_points.add(len(vals))
        for i, v in enumerate(vals):
            kp = fc.keyframe_points[i]
            kp.co = (i + 1, v)
            kp.interpolation = "LINEAR"
        fc.update()
    action.use_frame_range = True
    action.frame_start, action.frame_end = 1, len(frames)


acts = bpy.data.actions
report = {"source": SRC, "idle": IDLE, "move": MOVE, "attack": ATTACK}

# --- move: best loop window, then flatten the root's horizontal travel -------------------------------
run = acts[MOVE]
H, f0 = bone_heads(run)
R = root_world(run)
n = len(H)
best = None
for length in range(CYCLE_MIN, min(CYCLE_MAX, n - 1) + 1):
    for start in range(0, n - length):
        err = float(np.abs(H[start + length] - H[start]).mean())
        if best is None or err < best[0]:
            best = (err, start, length)
err, start, length = best
first, last = f0 + start, f0 + start + length     # last pose == first pose: drop the duplicate when looping
travel = R[start + length] - R[start]
horiz = float(np.hypot(travel[0], travel[1]))
report["move_window"] = [first, last - 1]
report["move_loop_err"] = round(err, 5)
report["travel_per_frame"] = round(horiz / length, 5)
print(f"move: frames {first}..{last - 1} ({length} frames), loop error {err:.4f}, "
      f"travel {horiz:.3f} units = {horiz / length:.4f} per frame", flush=True)
rest = arm.data.bones[ROOT].matrix_local.to_3x3()
drift = {}                                       # root channel -> (offset at the window start, per-frame drift)
for fc in run.fcurves:
    if fc.data_path != f'pose.bones["{ROOT}"].location':
        continue
    if abs(rest.col[fc.array_index][2]) > 0.7:   # this channel moves him up/down: keep the bob
        continue
    drift[fc.array_index] = (fc.evaluate(first) - fc.evaluate(f0), (fc.evaluate(last) - fc.evaluate(first)) / length)
trim(run, first, last - 1)
for fc in run.fcurves:
    if fc.data_path != f'pose.bones["{ROOT}"].location' or fc.array_index not in drift:
        continue
    offset, slope = drift[fc.array_index]       # back over his start spot, and no travel
    for kp in fc.keyframe_points:
        d = offset + slope * (kp.co[0] - 1)
        kp.co[1] -= d
        kp.handle_left[1] -= d
        kp.handle_right[1] -= d
    fc.update()
R2 = root_world(run)
report["move_root_horizontal_left"] = round(float(np.ptp(R2[:, :2], axis=0).max()), 4)
report["move_root_start_offset"] = [round(float(v), 4) for v in R2[0, :2] - R[0, :2]]
print("move: root horizontal range after flattening", report["move_root_horizontal_left"],
      "start offset from the clip's first frame", report["move_root_start_offset"], flush=True)

# --- attack: the window ------------------------------------------------------------------------------
splice(acts[ATTACK], ATTACK_FRAMES)
report["attack_window"] = ATTACK_FRAMES

# --- idle: as is -------------------------------------------------------------------------------------
idle = acts[IDLE]
idle.use_frame_range = True
idle.frame_start, idle.frame_end = (int(round(v)) for v in idle.frame_range)

for name, act in ((IDLE, idle), (MOVE, run), (ATTACK, acts[ATTACK])):
    act.name = {IDLE: "idle", MOVE: "move", ATTACK: "attack"}[name]
    act.use_fake_user = True
for a in list(acts):
    if a.name not in ("idle", "move", "attack"):
        acts.remove(a)
ad.action = None
for o in bpy.data.objects:
    if o.type == "MESH":
        for m in o.modifiers:
            m.show_viewport = True
report["frames"] = {a.name: [int(a.frame_start), int(a.frame_end)] for a in acts}
report["fps"] = scene.render.fps
bpy.ops.wm.save_as_mainfile(filepath=OUT)
with open(os.path.splitext(OUT)[0] + ".json", "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=1)
print("PLAYER_CLIPS_OK", OUT, report["frames"], flush=True)
