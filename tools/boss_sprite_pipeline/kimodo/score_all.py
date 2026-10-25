"""Score every cell in the pulled set, grouped by the plan's categories.

    score_all.py <kruns> <out.csv>

Pure BVH parsing, no Blender - the same hip/peak metrics the sheets print, so the table and the
images cannot disagree. hip is converted from the file's centimetres to metres.
"""
import collections
import glob
import os
import re
import sys

import numpy as np

SRC, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])

CATS = [("M_models", r"(Kimodo-SOMA|RPv1_1|SEEDv1_1)"), ("M3_model_seeds", r"M3_"),
        ("Mplus_steps", r"O_steps"), ("B0_baseline", r"B0_"), ("B1_duration", r"B1_"),
        ("B1b_bug", r"B1b_"), ("C_chaining", r"C[1-7]_"), ("Cplus_depth", r"Cp_"),
        ("CW_chain_wording", r"CW_"), ("N_constraints", r"N[1-4]_"), ("G_guidance", r"G_"),
        ("W_wording", r"W_"), ("O_oneoffs", r"O_(nopost|tpose)"), ("P_prompts", r"P_")]


def metrics(path):
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
            names.append(cur); chans.append(m2.group(2).split()); cur = None
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
    hipj = off.get("Hips") or list(off.values())[0]
    hy = hipj.get("Yposition")
    peak = float(step.max())
    act = float((step > peak * 0.25).mean())
    return len(A), (float(np.ptp(A[:, hy])) / 100.0 if hy is not None else 0.0), peak, act


def cat(name):
    for c, pat in CATS:
        if re.match(pat, name):
            return c
    return "?"


out = [("category", "cell", "frames", "hip_m", "peak", "active", "verdict")]
tally = collections.defaultdict(collections.Counter)
best = collections.defaultdict(list)
for d in sorted(glob.glob(os.path.join(SRC, "*"))):
    fs = sorted(glob.glob(os.path.join(d, "*.bvh")))
    if not fs:
        continue
    n = os.path.basename(d)
    m = metrics(fs[0])
    if not m:
        continue
    fr, hip, peak, act = m
    v = "DEAD" if (hip < 0.05 and peak < 60) else ("weak" if peak < 120 else "MOVES")
    c = cat(n)
    tally[c][v] += 1
    best[c].append((peak, hip, n))
    out.append((c, n, fr, "%.3f" % hip, "%.0f" % peak, "%.2f" % act, v))

open(OUT, "w").write("\n".join(",".join(str(x) for x in r) for r in out))
print("%-18s %5s %5s %5s   %s" % ("category", "MOVES", "weak", "DEAD", "strongest cell"))
for c, _ in CATS:
    t = tally[c]
    top = max(best[c])[2] if best[c] else "-"
    tp = max(best[c])[0] if best[c] else 0
    print("%-18s %5d %5d %5d   %s (peak %.0f)" % (c, t["MOVES"], t["weak"], t["DEAD"], top, tp))
print("\nrows", len(out) - 1, "->", OUT)
