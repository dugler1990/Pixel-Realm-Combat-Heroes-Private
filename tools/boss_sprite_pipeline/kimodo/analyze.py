"""Answer each block's question from the BVH, both samples per cell.

    analyze.py <runs_dir>

score_all.py reads the first sample only, which is how the first model comparison produced a
ranking that flipped depending on which sample was scored. Everything here averages the samples
and prints the spread, so a difference inside the noise is visible as one.
"""
import glob
import os
import re
import sys

import numpy as np

SRC = os.path.abspath(sys.argv[1])


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
    hipj = off.get("Hips") or list(off.values())[0]
    hy = hipj.get("Yposition")
    peak = float(step.max())
    return dict(frames=len(A), hip=float(np.ptp(A[:, hy])) / 100.0 if hy is not None else 0.0,
                peak=peak, active=float((step > peak * 0.25).mean()))


CELL = {}
for d in sorted(glob.glob(os.path.join(SRC, "*"))):
    fs = sorted(glob.glob(os.path.join(d, "*.bvh")))
    if not fs:
        continue
    ms = [m for m in (metrics(f) for f in fs) if m]
    if not ms:
        continue
    rec = {k: (float(np.mean([m[k] for m in ms])), float(np.ptp([m[k] for m in ms])))
           for k in ("hip", "peak", "active")}
    rec["n"] = len(ms)
    CELL[os.path.basename(d)] = rec


def get(name, key="peak"):
    c = CELL.get(name)
    return c[key][0] if c else None


def table(title, rows, note=""):
    print("\n### %s" % title)
    if note:
        print(note)
    if not rows:
        print("  (no cells)")
        return
    w = max(len(r[0]) for r in rows)
    for r in rows:
        print("  %-*s  %s" % (w, r[0], r[1]))


ACT3 = ["haymaker", "groundsmash", "jump"]
ACT5 = ACT3 + ["damage", "slap"]
TWO = ["haymaker", "groundsmash"]


def across(fmt, acts=ACT3, key="peak"):
    """Mean of a variant across its actions, and how many of those actions exist."""
    vals = [get(fmt % a, key) for a in acts]
    vals = [v for v in vals if v is not None]
    return (float(np.mean(vals)) if vals else None), len(vals)


rows = []
for tag, fmt in (("RP-v1", "Kimodo-SOMA-RP-v1__%s"), ("SEED-v1", "Kimodo-SOMA-SEED-v1__%s"),
                 ("RP-v1.1", "RPv1_1_%s"), ("SEED-v1.1", "SEEDv1_1_%s")):
    m, n = across(fmt)
    if m:
        rows.append((tag, "peak %5.0f   (%d actions)" % (m, n)))
table("M - models, one seed", rows)

rows = []
for tag in ("RPv1", "SEEDv11"):
    for a in ACT3:
        vs = [get("M3_%s_%s_s%d" % (tag, a, s)) for s in (11, 22, 33)]
        vs = [v for v in vs if v]
        if vs:
            rows.append(("%-8s %-12s" % (tag, a),
                         "peak %5.0f   seeds %s" % (np.mean(vs),
                                                    " ".join("%.0f" % v for v in vs))))
table("M3 - the same models over three seeds", rows,
      "  the spread across seeds decides whether a model difference is real")

rows = []
for s in (50, 250):
    m, _ = across("O_steps%d_%%s" % s, TWO)
    if m:
        rows.append(("%d steps" % s, "peak %5.0f" % m))
d, _ = across("B1_none_4s_%s", TWO)
rows.append(("100 steps (default)", "peak %5.0f" % d))
table("M+ - denoising steps", rows, "  same prompt and 4.0s, only the step count differs")

rows = []
for d in (2, 3, 4, 5, 6, 8):
    n_, _ = across("B1_none_%ds_%%s" % d, TWO)
    f_, _ = across("B1_fit_%ds_%%s" % d, TWO)
    hn, _ = across("B1_none_%ds_%%s" % d, TWO, "hip")
    hf, _ = across("B1_fit_%ds_%%s" % d, TWO, "hip")
    if n_ and f_:
        rows.append(("%ds" % d, "no anchor  peak %5.0f hip %.2f    |    fitted  peak %5.0f hip %.2f"
                     % (n_, hn, f_, hf)))
table("B1 - clip length, with and without an anchor fitted to that length", rows)

rows = []
for a in TWO + ["jump", "damage"]:
    st = get("B1b_stale_8s_" + a)
    if st:
        fit, non = get("B1_fit_8s_" + a), get("B1_none_8s_" + a)
        rows.append((a, "stale-150 %5.0f    |    fitted-240 %s    |    no anchor %s"
                     % (st, "%5.0f" % fit if fit else "  -  ",
                        "%5.0f" % non if non else "  -  ")))
table("B1b - an 8s clip driven by the 150-frame constraint file", rows)

rows = []
for tag, fmt in (("C1  balanced 1/2.5/1", "C1_bal_%s"),
                 ("C2  long action .5/4/.5", "C2_longact_%s"),
                 ("C3  even 2/2/2", "C3_even_%s"),
                 ("C4  combat stance bookends", "C4_stance_%s"),
                 ("C5  transition 15 frames", "C5_trans_%s"),
                 ("C6  chain + fitted constraint", "C6_conschain_%s"),
                 ("C7  UNCHAINED control", "C7_nochain_%s"),
                 ("C+  five chunks", "Cp_5chunk_%s")):
    m, n = across(fmt)
    h, _ = across(fmt, key="hip")
    if m:
        rows.append((tag, "peak %5.0f   hip %.2f   (%d actions)" % (m, h, n)))
table("C - chaining, against the unchained control", rows)

rows = []
for cfg in ("C2", "C4"):
    for w in ("drunk", "heavy"):
        m, _ = across("CW_%s_%s_%%s" % (cfg, w))
        if m:
            rows.append(("%s split x %s wording" % (cfg, w), "peak %5.0f" % m))
table("CW - wording inside the chain", rows)

rows = []
for tag, fmt in (("FullBody (all 77 joints)", "N1_full_%s"), ("Root2D", "N2_root2d_%s"),
                 ("EndEffector", "N3_endeff_%s"), ("Hands", "N4_hands_%s")):
    m, _ = across(fmt)
    h, _ = across(fmt, key="hip")
    if m:
        rows.append((tag, "peak %5.0f   hip %.2f" % (m, h)))
table("N - constraint class, same prompt and length", rows)

rows = []
for tag, fmt in (("nocfg", "G_nocfg_%s"), ("regular 3.0", "G_regular_%s"),
                 ("separated 3.0/6.0", "G_sep6_%s"), ("separated 3.0/1.0", "G_sep1_%s")):
    m, _ = across(fmt, TWO)
    if m:
        rows.append((tag, "peak %5.0f" % m))
d, _ = across("C1_bal_%s", TWO)
rows.append(("separated 3.0/2.0 (default)", "peak %5.0f" % d))
table("G - guidance, all on the same chained prompt", rows)

rows = []
for tag, fmt in (("drunk / sloppy", "W_drunk_%s"), ("heavy / planted", "W_heavy_%s"),
                 ("single clause", "W_single_%s"), ("no creature named", "W_nocre_%s")):
    m, n = across(fmt, ACT5)
    h, _ = across(fmt, ACT5, "hip")
    if m:
        rows.append((tag, "peak %5.0f   hip %.2f   (%d actions)" % (m, h, n)))
table("W - wording, all 5 actions, 4.0s, no constraint", rows)

rows = []
for tag, fmt in (("V1  plain, idle stated", "P_V1_%s"),
                 ("V2  styled (angry / injured)", "P_V2_%s"),
                 ("V3  body-mechanics wording", "P_V3_%s"),
                 ("K1  stance/act/stance 1-2.5-1", "P_K1_%s"),
                 ("K2  stance/act/stance 1-4-1", "P_K2_%s"),
                 ("K3  five beats, wind-up named", "P_K3_%s"),
                 ("K4  five beats, styled strike", "P_K4_%s"),
                 ("K5  windup/act/recover-idle", "P_K5_%s")):
    m, _ = across(fmt, ACT5)
    h, _ = across(fmt, ACT5, "hip")
    ac, _ = across(fmt, ACT5, "active")
    if m:
        rows.append((tag, "peak %5.0f   hip %.2f   active %.0f%%" % (m, h, ac * 100)))
table("P - the rewritten prompts, mean over all 5 actions", rows)

print("\n### P - the three strongest variants per action")
for a in ACT5:
    cand = [(get("P_%s_%s" % (v, a)), v)
            for v in ("V1", "V2", "V3", "K1", "K2", "K3", "K4", "K5")]
    cand = [(p, v) for p, v in cand if p]
    cand.sort(reverse=True)
    print("  %-12s %s" % (a, "   ".join("%s %.0f" % (v, p) for p, v in cand[:3])))

rows = []
for tag, fmt in (("post-processing OFF", "O_nopost_%s"), ("T-pose rest on export", "O_tpose_%s")):
    m, _ = across(fmt, TWO)
    if m:
        rows.append((tag, "peak %5.0f" % m))
d, _ = across("B1_none_4s_%s", TWO)
rows.append(("default", "peak %5.0f" % d))
table("O - defaults", rows)

sp = [c["peak"][1] for c in CELL.values() if c["n"] > 1]
pk = [c["peak"][0] for c in CELL.values() if c["n"] > 1]
print("\n### How big a difference is real")
print("  %d cells with 2 samples: median sample-to-sample peak gap %.0f, mean peak %.0f"
      % (len(sp), np.median(sp), np.mean(pk)))
print("  a gap under ~%.0f between two variants is inside the noise of a single draw."
      % np.median(sp))
