"""Score raw Kimodo BVH - no Blender, no retarget, no render. `score_raw.py <dir> [<dir>...]`

Channel offsets are parsed from the CHANNELS lines, not assumed: the root carries 6 channels
(position + rotation) and the rest usually 3, so a flat i*6 indexes off the end of the array.

hip_range is the discriminator - a real jump measured 0.383, a collapsed one 0.019. hand is its
attack equivalent: how far the wrists travel relative to the hips. peak is the fastest single
frame; an attack needs one.
"""
import glob
import os
import re
import sys

import numpy as np


def load(p):
    names, chans, rows, seen, cur = [], [], [], False, None
    for line in open(p):
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
    off, k = {}, 0
    for n, cs in zip(names, chans):
        off[n] = {c: k + i for i, c in enumerate(cs)}
        k += len(cs)
    return off, np.array(rows)


def score(p):
    off, A = load(p)
    if A.size == 0 or len(A) < 4:
        return None
    rot_cols = [i for j in off.values() for c, i in j.items() if c.endswith("rotation")]
    R = np.degrees(np.unwrap(np.radians(A[:, rot_cols]), axis=0))
    step = np.abs(np.diff(R, axis=0)).sum(axis=1)
    hipj = off.get("Hips") or off.get("Root") or list(off.values())[0]
    def pos(j, ax):
        c = j.get(ax + "position")
        return A[:, c] if c is not None else None
    hy = pos(hipj, "Y")
    hip_range = float(np.ptp(hy)) if hy is not None else 0.0
    hand = 0.0
    hx, hz = pos(hipj, "X"), pos(hipj, "Z")
    for w in ("LeftHand", "RightHand", "LeftForeArm", "RightForeArm"):
        j = off.get(w)
        if not j or hx is None:
            continue
        wx, wz = pos(j, "X"), pos(j, "Z")
        if wx is None:
            continue
        hand = max(hand, float(np.ptp(np.hypot(wx - hx, wz - hz))))
    return dict(frames=len(A), hip=hip_range, hand=hand, peak=float(step.max()),
                active=100.0 * float((step > step.max() * 0.25).mean()))


rows = []
for root in sys.argv[1:]:
    for d in sorted(glob.glob(os.path.join(os.path.abspath(root), "*"))):
        fs = glob.glob(os.path.join(d, "**", "*.bvh"), recursive=True) if os.path.isdir(d) else []
        ss = [s for s in (score(f) for f in fs) if s]
        if not ss:
            continue
        rows.append((os.path.basename(d), len(ss),
                     np.median([s["frames"] for s in ss]), np.median([s["hip"] for s in ss]),
                     np.median([s["hand"] for s in ss]), np.median([s["peak"] for s in ss]),
                     np.median([s["active"] for s in ss])))
rows.sort(key=lambda r: -r[5])
print("%-42s %2s %5s %8s %8s %7s %6s  %s" % ("cell", "n", "frm", "hip", "hand", "peak", "act%", "verdict"))
for n, c, fr, hp, hd, pk, ac in rows:
    v = "DEAD" if (hp < 0.05 and pk < 60) else ("weak" if pk < 120 else "MOVES")
    print("%-42s %2d %5.0f %8.3f %8.3f %7.0f %5.0f%%  %s" % (n, c, fr, hp, hd, pk, ac, v))
