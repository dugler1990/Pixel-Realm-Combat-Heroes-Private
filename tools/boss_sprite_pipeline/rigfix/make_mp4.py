"""PNG frame folders -> one mp4 each. `python make_mp4.py <dir> [fps]`"""
import glob
import os
import sys

import cv2

ROOT = os.path.abspath(sys.argv[1])
FPS = float(sys.argv[2]) if len(sys.argv) > 2 else 16.0

for d in sorted(p for p in glob.glob(os.path.join(ROOT, "*")) if os.path.isdir(p)):
    pngs = sorted(glob.glob(os.path.join(d, "*.png")))
    if not pngs:
        continue
    imgs = [cv2.imread(p) for p in pngs]
    h, w = imgs[0].shape[:2]
    out = os.path.join(ROOT, os.path.basename(d) + ".mp4")
    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (w, h))
    for _ in range(2):                                   # two loops, they are short
        for im in imgs:
            vw.write(im)
    vw.release()
    print("wrote", out, len(imgs), "frames", flush=True)
print("MP4_OK")
