"""Rank every Kimodo take per prompt, reading BVH directly - no Blender, no GPU.

    python clip_score.py <dir> [<dir> ...]

Takes used to be rejected by eye, and any take whose eulers wrapped looked broken whether or not
the motion was. bvh_unwrap.py showed the wrap is a number problem, not a motion problem, so the
takes rejected for it are still on the table - but there are 139 of them across the pools and
watching each one is not the way to choose.

Each take is unwrapped in memory first, then scored:

  pop     largest single-frame rotation step, over all channels, after unwrapping. A real pop -
          the retargeter interpolating through a discontinuity - survives unwrapping. Low is good.
  energy  mean per-frame rotation speed. Separates a clip that does something from a clip that
          stands there; an attack wants this high, an idle low.
  ret     how far the last pose is from the first, RMS over channels. Low means the clip ends
          where it began, so it chains back into idle without a blend.
  drift   how far the root travelled in the ground plane, in BVH units.

Nothing here decides for you - it orders the takes so the eye is spent on the top two.
"""
import glob
import os
import sys

import numpy as np


def read_bvh(path):
    head, rows, in_motion = [], [], False
    for line in open(path):
        if in_motion:
            v = line.split()
            if v and v[0][0].isdigit() or (v and v[0].startswith("-")):
                rows.append([float(x) for x in v])
        else:
            head.append(line)
            if line.strip().startswith("Frame Time"):
                in_motion = True
    return np.array(rows, dtype=np.float64)


def score(path):
    A = read_bvh(path)
    if A.ndim != 2 or len(A) < 4:
        return None
    rot = np.ones(A.shape[1], bool)
    rot[:3] = False                                    # first three channels are root translation
    R = np.degrees(np.unwrap(np.radians(A[:, rot]), axis=0))
    d = np.abs(np.diff(R, axis=0))
    root = A[:, :3]
    return dict(
        frames=len(A),
        pop=float(d.max()),
        energy=float(d.sum(axis=1).mean()),
        ret=float(np.sqrt(((R[-1] - R[0]) ** 2).mean())),
        drift=float(np.hypot(root[-1, 0] - root[0, 0], root[-1, 2] - root[0, 2])),
    )


files = []
for d in sys.argv[1:]:
    files += glob.glob(os.path.join(d, "**", "*.bvh"), recursive=True)

groups = {}
for f in sorted(files):
    stem = os.path.splitext(os.path.basename(f))[0]
    prompt = stem.rsplit("_", 1)[0] if stem.rsplit("_", 1)[-1].isdigit() else stem
    s = score(f)
    if s:
        groups.setdefault(prompt, []).append((stem, s))

print("%-22s %5s %7s %8s %7s %7s" % ("take", "frm", "pop", "energy", "ret", "drift"), flush=True)
for prompt in sorted(groups):
    takes = groups[prompt]
    # a pop is disqualifying; among clean takes prefer the one that returns closest to its start
    takes.sort(key=lambda t: (t[1]["pop"] > 25.0, t[1]["ret"]))
    print("-- %s" % prompt, flush=True)
    for i, (stem, s) in enumerate(takes):
        mark = " <-- best" if i == 0 and s["pop"] <= 25.0 else (" (all popped)" if i == 0 else "")
        print("%-22s %5d %7.1f %8.1f %7.1f %7.2f%s" % (
            stem, s["frames"], s["pop"], s["energy"], s["ret"], s["drift"], mark), flush=True)
