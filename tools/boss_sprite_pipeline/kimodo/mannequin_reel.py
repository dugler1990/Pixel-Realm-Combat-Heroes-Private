"""Mannequin frames -> one labelled reel. `mannequin_reel.py <mann_dir> <out.mp4> [manifest.json]`

mannequin.py writes two camera angles per frame (`NNNN_0.png`, `NNNN_1.png`). They are paired
side by side here, and the cell name, model, parameters and prompt are drawn on top - the same
rule as the stick-figure reels: nothing needs a separate key to be readable.
"""
import glob
import json
import os
import sys
import textwrap

import cv2

SRC, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
MAN = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else {}
FPS = float(sys.argv[4]) if len(sys.argv) > 4 else 15.0
F = cv2.FONT_HERSHEY_SIMPLEX
HDR = 104

dirs = sorted(d for d in glob.glob(os.path.join(SRC, "[0-9]*")) if os.path.isdir(d))
if not dirs:
    print("NO CELLS in", SRC)
    raise SystemExit(1)

probe = cv2.imread(sorted(glob.glob(os.path.join(dirs[0], "*_0.png")))[0])
h, w = probe.shape[:2]
W, H = w * 2, h + HDR
vw = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))

total = 0
for d in dirs:
    cell = os.path.basename(d).split("_", 1)[1]
    meta = MAN.get(cell, {})
    for p0 in sorted(glob.glob(os.path.join(d, "*_0.png"))):
        p1 = p0[:-6] + "_1.png"
        a = cv2.imread(p0)
        b = cv2.imread(p1) if os.path.exists(p1) else a
        pair = cv2.hconcat([a, b])
        canvas = cv2.copyMakeBorder(pair, HDR, 0, 0, 0, cv2.BORDER_CONSTANT, value=(24, 24, 30))
        cv2.putText(canvas, cell[:52], (14, 30), F, 0.72, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(canvas, cell[:52], (13, 29), F, 0.72, (70, 225, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, meta.get("params", "")[:95], (14, 54), F, 0.42,
                    (255, 190, 110), 1, cv2.LINE_AA)
        for i, ln in enumerate(textwrap.wrap(meta.get("prompt", ""), 104)[:2]):
            cv2.putText(canvas, ln, (14, 76 + i * 18), F, 0.40, (205, 205, 215), 1, cv2.LINE_AA)
        vw.write(canvas)
        total += 1
    print("  %-40s" % os.path.basename(d)[:40], flush=True)
vw.release()
print("MANN_REEL", OUT, len(dirs), "cells", total, "frames", "%dx%d" % (W, H), flush=True)
