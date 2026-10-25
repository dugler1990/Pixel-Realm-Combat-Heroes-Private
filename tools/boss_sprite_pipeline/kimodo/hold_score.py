"""Rank clips by how long they HOLD a distinctive pose, not by how sharply they move.

    hold_score.py <cells_dir> [name_filter]

Peak degrees-per-frame ranks a strike well and a held pose badly. The roar cells proved it:
X_S_roar scored 386-401 by throwing the arms up for two frames and returning to idle, while
X_K_roar scored 156 and actually held arms-spread across the middle of the clip. Peak rewards
the spike and penalises the hold, which is backwards for a roar, a guard or a taunt.

  reach  how far the clip ever gets from its own resting pose, in summed degrees.
  hold   longest run of consecutive frames spent NEAR THE EXTREME POSE (within 30% of reach),
         as a fraction of the clip.

The resting pose is the per-channel MEDIAN over the clip, not frame 0. Measuring from frame 0
scores a clip that starts in the key pose, drops to idle and stays there as a near-total "hold"
- of the idle. The median is whatever the body spends most of its time near, so distance from
it is distance from rest however the clip is ordered.

A strike wants high peak and low hold. A roar wants high reach and high hold.
Averaged over every sample of the cell, because one draw carries +/-79 on peak alone.
"""
import glob
import os
import re
import sys

import numpy as np

SRC = os.path.abspath(sys.argv[1])
PAT = re.compile(sys.argv[2]) if len(sys.argv) > 2 else None


def curves(path):
    names, chans, rows, seen, cur = [], [], [], False, None
    for line in open(path):
        s = line.strip()
        if seen:
            v = line.split()
            if v:
                rows.append([float(x) for x in v])
            continue
        m = re.match(r"(?:ROOT|JOINT)\s+(\S+)", s)
        if m:
            cur = m.group(1)
        m2 = re.match(r"CHANNELS\s+(\d+)\s+(.*)", s)
        if m2 and cur is not None:
            names.append(cur)
            chans.append(m2.group(2).split())
            cur = None
        if s.startswith("Frame Time"):
            seen = True
    A = np.array(rows)
    if A.size == 0:
        return None
    off, k = {}, 0
    for n, cs in zip(names, chans):
        off[n] = {c: k + i for i, c in enumerate(cs)}
        k += len(cs)
    rc = [i for j in off.values() for c, i in j.items() if c.endswith("rotation")]
    R = np.degrees(np.unwrap(np.radians(A[:, rc]), axis=0))
    step = np.abs(np.diff(R, axis=0)).sum(axis=1)
    rest = np.median(R, axis=0)                  # the pose the body spends most time near
    dist = np.abs(R - rest).sum(axis=1)
    extreme = R[int(np.argmax(dist))]
    near = np.abs(R - extreme).sum(axis=1)       # distance from the most extreme pose
    return step, dist, near


def longest_run(mask):
    best = run = 0
    for v in mask:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


rows = []
for d in sorted(glob.glob(os.path.join(SRC, "*"))):
    n = os.path.basename(d)
    if PAT and not PAT.search(n):
        continue
    fs = sorted(glob.glob(os.path.join(d, "*.bvh")))
    if not fs:
        continue
    peaks, holds, reaches = [], [], []
    for f in fs:
        c = curves(f)
        if not c:
            continue
        step, dist, near = c
        reach = float(dist.max())
        if reach <= 0:
            continue
        peaks.append(float(step.max()))
        reaches.append(reach)
        holds.append(longest_run(near <= 0.30 * reach) / len(near))
    if peaks:
        rows.append((float(np.mean(holds)), float(np.mean(reaches)), float(np.mean(peaks)),
                     n, len(peaks)))

rows.sort(reverse=True)
print("%-34s %6s %8s %7s  %s" % ("cell", "hold", "reach", "peak", "n"))
for h, r, p, n, c in rows:
    print("%-34s %5.0f%% %8.0f %7.0f  %d" % (n, h * 100, r, p, c))
