"""Second pass for a two-handed clip: pin both hands together on one grip, from a first-pass clip's own motion.

    python build_twohand_cons.py <first_pass.npz> <out.json> [--every 8] [--gap 0.09]

Takes the first pass's joints (driver.py saves them beside each BVH). Every --every frames (and the last), the left
hand is moved to the right hand plus --gap metres toward where the left hand already is (a fist apart on the hilt,
in the clip's own direction); the right hand stays where the clip put it. Both hands are written as an
EndEffectorConstraintSet (LeftHand, RightHand; the root path and heading from the same clip), so the regenerated clip
swings like the first one with the hands together. Use with the same prompt and duration (frame indices are absolute).
"""
import argparse

import numpy as np
import torch
import kimodo.constraints as kc

ap = argparse.ArgumentParser()
ap.add_argument("npz")
ap.add_argument("out")
ap.add_argument("--every", type=int, default=8)
ap.add_argument("--gap", type=float, default=0.09)
a = ap.parse_args()

d = np.load(a.npz, allow_pickle=True)
skel = kc.SOMASkeleton77()
names = list(skel.bone_order_names)
L, R = names.index("LeftHand"), names.index("RightHand")
pos = np.asarray(d["posed_joints"], dtype=np.float32).copy()
rot = np.asarray(d["global_rot_mats"], dtype=np.float32)
F = len(pos)
idx = sorted(set(list(range(0, F, a.every)) + [F - 1]))
for f in idx:
    v = pos[f, L] - pos[f, R]
    n = float(np.linalg.norm(v))
    v = v / n if n > 1e-6 else np.array([0, -1, 0], np.float32)
    pos[f, L] = pos[f, R] + v * a.gap
sel = torch.tensor(idx)
gp = torch.tensor(pos)[sel]
gr = torch.tensor(rot)[sel]
sr = torch.tensor(np.asarray(d["smooth_root_pos"], dtype=np.float32))[:, [0, 2]][sel]
cs = kc.EndEffectorConstraintSet(skel, sel, gp, gr, sr, joint_names=["LeftHand", "RightHand"])
kc.save_constraints_lst(a.out, [cs])
print("TWOHAND_CONS", a.out, len(idx), "frames of", F, flush=True)
