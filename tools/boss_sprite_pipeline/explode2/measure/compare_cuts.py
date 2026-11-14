"""How much does the cut change as views are added? Finds the view count worth paying for.

    python compare_cuts.py <out.png> <run_dir> [<run_dir> ...] [--diag <file>]

Each run_dir is an explode_label.py --out folder (labels_face.npy, parts.json, PARTS_SHEET.png), given
in increasing view count (e.g. --dirs 16, 32, 64, 128 on the same masks). Parts are matched by name.
Prints, for each run against the next one and against the last (largest) one, the share of faces
whose part differs, overall and per part of the larger run. When adding views stops changing the cut,
more views are wasted time. <out.png>: the runs' PARTS_SHEET.png stacked, labelled.
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

argv = sys.argv[1:]
DIAG_OUT = None
if "--diag" in argv:
    i = argv.index("--diag")
    DIAG_OUT = os.path.abspath(argv[i + 1])
    del argv[i:i + 2]
OUT_PNG, RUNS = os.path.abspath(argv[0]), [os.path.abspath(r) for r in argv[1:]]


def load(run):
    names = json.load(open(os.path.join(run, "parts.json")))["parts"]
    return np.array(names, dtype=object)[np.load(os.path.join(run, "labels_face.npy"))]


labels = [load(r) for r in RUNS]
res = {}


def diff(a, b, title):
    ch = a != b
    per = {p: round(100 * float(ch[b == p].mean()), 2) for p in sorted(set(b.tolist()))}
    print(f"{title}: {100 * ch.mean():.2f}% of faces change part  "
          + "  ".join(f"{p} {v:.1f}" for p, v in per.items()), flush=True)
    res[title] = {"all": round(100 * float(ch.mean()), 2), "by_part": per}


for k in range(len(RUNS) - 1):
    diff(labels[k], labels[k + 1], f"{os.path.basename(RUNS[k])} -> {os.path.basename(RUNS[k + 1])}")
for k in range(len(RUNS) - 1):
    diff(labels[k], labels[-1], f"{os.path.basename(RUNS[k])} vs {os.path.basename(RUNS[-1])}")

sheets = [Image.open(os.path.join(r, "PARTS_SHEET.png")).convert("RGB") for r in RUNS]
W = max(s.width for s in sheets)
LAB = 40
img = Image.new("RGB", (W, sum(s.height + LAB for s in sheets)), (25, 25, 28))
d = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype("arial.ttf", 28)
except OSError:
    font = ImageFont.load_default()
y = 0
for r, s in zip(RUNS, sheets):
    d.text((10, y + 6), os.path.basename(r), fill=(235, 235, 235), font=font)
    img.paste(s, (0, y + LAB))
    y += s.height + LAB
img.save(OUT_PNG)
if DIAG_OUT:
    json.dump({"step": "5 cut vs view count", "out": OUT_PNG, "settings": {"runs": RUNS},
               "results": {k: v["all"] for k, v in res.items()}}, open(DIAG_OUT, "w"), indent=1)
print("COMPARE_OK", OUT_PNG)
