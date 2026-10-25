"""Remove euler wraparound from BVH rotation channels.

    python bvh_unwrap.py <in_dir> <out_dir>

A BVH stores rotations as euler angles, so a joint passing through +-180 degrees jumps a full
turn between consecutive frames. Nothing is wrong with the motion - the numbers wrapped - but
any per-frame difference measure sees a 300+ degree spike, and a retargeter that interpolates
them produces a visible pop.

At 8 seconds this hit 6 of 10 clips, against roughly 1 in 3 at 5 seconds: longer clips
accumulate more rotation, so they cross the boundary more often. Rejecting those clips would
throw away good takes.

Fix: walk each rotation channel and add or subtract 360 whenever the step exceeds 180, so the
channel becomes continuous. Positions are untouched.
"""
import glob
import os
import sys

import numpy as np

SRC, DST = (os.path.abspath(p) for p in sys.argv[1:3])
os.makedirs(DST, exist_ok=True)

for f in sorted(glob.glob(os.path.join(SRC, "*.bvh"))):
    head, rows, seen = [], [], False
    for line in open(f):
        if seen:
            v = line.split()
            if len(v) > 3:
                rows.append([float(x) for x in v])
        else:
            head.append(line)
            if line.startswith("Frame Time"):
                seen = True
    if not rows:
        continue
    A = np.array(rows)
    # channel layout: the root has 6 (3 position, 3 rotation), every other joint has 3 rotation
    rot = np.ones(A.shape[1], bool)
    rot[:3] = False                       # root translation
    before = np.abs(np.diff(A[:, rot], axis=0)).max()
    unwrapped = np.degrees(np.unwrap(np.radians(A[:, rot]), axis=0))
    A[:, rot] = unwrapped
    after = np.abs(np.diff(A[:, rot], axis=0)).max()
    out = os.path.join(DST, os.path.basename(f))
    with open(out, "w") as fh:
        fh.writelines(head)
        for r in A:
            fh.write(" ".join("%.6f" % x for x in r) + "\n")
    print("%-24s max step %7.1f -> %6.1f deg" % (os.path.basename(f)[:24], before, after),
          flush=True)
print("UNWRAP_OK ->", DST, flush=True)
