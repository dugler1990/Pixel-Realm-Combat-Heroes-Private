"""Build every constraint file the suite needs, from one generated idle clip.

    build_cons.py <idle.npz>

The npz carries posed_joints (T,77,3) global positions and global_rot_mats (T,77,3,3) global
rotations - those are what the constraint classes want.

frame_indices are absolute, so a set built for 150 frames pins the wrong frames in a 240-frame
clip. Each duration therefore gets its own file, and constraints.json is deliberately kept as
the 150-frame one so the stale-constraint failure can be reproduced on purpose.

Also emits the looser classes: we have only ever used FullBodyConstraintSet, which pins all 77
joints. Root2D pins only where he stands; EndEffector only hands and feet.
"""
import os
import shutil
import sys

import numpy as np
import torch
import kimodo.constraints as kc

d = np.load(sys.argv[1], allow_pickle=True)
OUT = "/workspace/cons"
os.makedirs(OUT, exist_ok=True)
skel = kc.SOMASkeleton77()

pos = torch.tensor(np.asarray(d["posed_joints"]), dtype=torch.float32)      # (T,77,3)
rot = torch.tensor(np.asarray(d["global_rot_mats"]), dtype=torch.float32)   # (T,77,3,3)
print("src", tuple(pos.shape), tuple(rot.shape), flush=True)

anchor_p = pos[:1]          # frame 0: the pose every clip returns to
anchor_r = rot[:1]

made = []
for FR in (60, 90, 120, 135, 150, 180, 240):
    idx = torch.tensor([0, FR - 1])
    gp = anchor_p.repeat(2, 1, 1)
    gr = anchor_r.repeat(2, 1, 1, 1)
    for cls, tag in ((kc.FullBodyConstraintSet, "full"),
                     (kc.Root2DConstraintSet, "root2d"),
                     (kc.EndEffectorConstraintSet, "endeff")):
        try:
            cs = cls(skel, idx, gp, gr)
            p = os.path.join(OUT, "%s_%d.json" % (tag, FR))
            kc.save_constraints_lst(p, [cs])
            made.append(os.path.basename(p))
        except Exception as e:
            print("  %-7s %3d FAILED %s" % (tag, FR, str(e)[:100]), flush=True)

for FR in (60, 90, 120, 135, 150, 180, 240):
    a = os.path.join(OUT, "full_%d.json" % FR)
    if os.path.exists(a):
        shutil.copy(a, os.path.join(OUT, "constraints_%d.json" % FR))
stale = os.path.join(OUT, "full_150.json")
if os.path.exists(stale):
    shutil.copy(stale, os.path.join(OUT, "constraints.json"))   # deliberately the wrong size
print("BUILT %d:" % len(made), sorted(set(made)), flush=True)
