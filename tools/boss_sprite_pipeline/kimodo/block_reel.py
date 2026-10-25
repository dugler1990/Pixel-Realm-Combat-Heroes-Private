"""cell_reel.py's numbered per-cell frame folders -> one labelled mp4 for the block.

    block_reel.py <reel_dir> <out.mp4> [fps]

cell_reel.py already burns the cell name, its parameters, its prompt and its scores into every
frame, so the reel needs no separate key: whatever is on screen says what produced it.
"""
import glob
import os
import sys

import cv2

SRC, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
FPS = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0

dirs = sorted(d for d in glob.glob(os.path.join(SRC, "[0-9]*")) if os.path.isdir(d))
if not dirs:
    print("NO CELL FOLDERS in", SRC)
    raise SystemExit(1)

first = sorted(glob.glob(os.path.join(dirs[0], "*.png")))[0]
h, w = cv2.imread(first).shape[:2]
vw = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (w, h))
total = 0
for d in dirs:
    pngs = sorted(glob.glob(os.path.join(d, "*.png")))
    for p in pngs:
        im = cv2.imread(p)
        if im.shape[:2] != (h, w):
            im = cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA)
        vw.write(im)
    total += len(pngs)
    print("  %-44s %3d frames" % (os.path.basename(d)[:44], len(pngs)), flush=True)
vw.release()
print("BLOCK_REEL", OUT, len(dirs), "cells", total, "frames", "%dx%d" % (w, h), flush=True)
