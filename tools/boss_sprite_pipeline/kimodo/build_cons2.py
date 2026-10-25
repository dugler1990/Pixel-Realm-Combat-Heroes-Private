"""The looser constraint classes, which is where the interesting ground is.

    build_cons2.py <idle.npz>

FullBodyConstraintSet pins all 77 joints - that is what we have always used and almost certainly
why anchored attacks go limp. These pin far less:
  root2d  where he stands, pose entirely free
  feet    feet return home, everything above the hips free to swing
  hands   hands return home
  endeff  hands and feet
"""
import os
import sys

import numpy as np
import torch
import kimodo.constraints as kc

d = np.load(sys.argv[1], allow_pickle=True)
OUT = "/workspace/cons"
os.makedirs(OUT, exist_ok=True)
skel = kc.SOMASkeleton77()

pos = torch.tensor(np.asarray(d["posed_joints"]), dtype=torch.float32)
rot = torch.tensor(np.asarray(d["global_rot_mats"]), dtype=torch.float32)
sr = torch.tensor(np.asarray(d["smooth_root_pos"]), dtype=torch.float32)[:, [0, 2]]  # x,z
hd = torch.tensor(np.asarray(d["global_root_heading"]), dtype=torch.float32)

SETS = {
    "feet":  ["LeftFoot", "RightFoot", "LeftToeBase", "RightToeBase"],
    "hands": ["LeftHand", "RightHand"],
    "endeff": ["LeftFoot", "RightFoot", "LeftHand", "RightHand"],
}
made = []
for FR in (60, 90, 120, 150, 180, 240):
    idx = torch.tensor([0, FR - 1])
    gp, gr = pos[:1].repeat(2, 1, 1), rot[:1].repeat(2, 1, 1, 1)
    s2, gh = sr[:1].repeat(2, 1), hd[:1].repeat(2, 1)
    try:
        cs = kc.Root2DConstraintSet(skel, idx, s2, global_root_heading=gh)
        p = "%s/root2d_%d.json" % (OUT, FR)
        kc.save_constraints_lst(p, [cs])
        made.append(os.path.basename(p))
    except Exception as e:
        print("root2d %d FAILED %s" % (FR, str(e)[:90]), flush=True)
    for tag, names in SETS.items():
        try:
            cs = kc.EndEffectorConstraintSet(skel, idx, gp, gr, s2, joint_names=names)
            p = "%s/%s_%d.json" % (OUT, tag, FR)
            kc.save_constraints_lst(p, [cs])
            made.append(os.path.basename(p))
        except Exception as e:
            print("%-6s %3d FAILED %s" % (tag, FR, str(e)[:90]), flush=True)
print("BUILT %d" % len(made), sorted(set(x.split("_")[0] for x in made)), flush=True)
