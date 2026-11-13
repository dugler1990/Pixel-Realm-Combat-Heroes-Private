"""How much of his body shows through the worn set, pose by pose: one number to drive down.

    python skin_metric.py <out.png> <frames_dir> [<frames_dir> ...] [--json <file>]

<frames_dir>: explode_pose.py --mask --hide-head output (the _frames_<label> folder of the stills, the
_anim_<clip> folders of the clips). In those renders every piece is grey, the background black, his head and
neck are taken out (his bare head is meant to show), and every visible body pixel is coloured by why it shows:
  green  armour right behind it along the camera ray: the body pokes through (a tuck / fit fault)
  cyan   no armour close behind: an opening or a hole in the armour (a coverage / cut fault)
Counts each single-view image (square; the 4-side strips of the clips are skipped): body pixels as a share of
the figure, split into the two. Prints the means, the worst ten and the share per view; <out.png> shows every
image with poking-through body red and openings blue over grey armour.
"""
import glob
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

argv = sys.argv[1:]
JSON_OUT = None
if "--json" in argv:
    i = argv.index("--json")
    JSON_OUT = os.path.abspath(argv[i + 1])
    del argv[i:i + 2]
OUT, DIRS = os.path.abspath(argv[0]), [os.path.abspath(a) for a in argv[1:]]

res, tiles = {}, []
for d in DIRS:
    for p in sorted(glob.glob(os.path.join(d, "*.png"))):
        im = Image.open(p).convert("RGB")
        if im.width != im.height:
            continue
        a = np.asarray(im)
        body = (a[..., 1] > 200) & (a[..., 0] < 60)
        opening = body & (a[..., 2] > 200)
        figure = a.max(2) > 20
        key = f"{os.path.basename(d).lstrip('_')}/{os.path.basename(p)[:-4]}"
        n = max(figure.sum(), 1)
        res[key] = {"body": round(100.0 * body.sum() / n, 3), "through": round(100.0 * (body & ~opening).sum() / n, 3),
                    "opening": round(100.0 * opening.sum() / n, 3)}
        out = np.where(figure[..., None], np.array([120, 120, 125], np.uint8), np.array([25, 25, 28], np.uint8))
        out[body & ~opening] = (255, 30, 30)
        out[opening] = (40, 140, 255)
        tiles.append((key, Image.fromarray(out), res[key]))
assert res, f"no square renders in {DIRS}"
mean = {k: float(np.mean([r[k] for r in res.values()])) for k in ("body", "through", "opening")}
per_view = {}
for k, r in res.items():
    per_view.setdefault(k.rsplit("_", 1)[-1], []).append(r["body"])
print(f"body visible: mean {mean['body']:.2f}% of the figure over {len(res)} images = poking through "
      f"{mean['through']:.2f}% + openings {mean['opening']:.2f}% "
      f"({sum(r['body'] > 0.05 for r in res.values())} images over 0.05%)")
print("  per view: " + ", ".join(f"{v} {np.mean(x):.2f}%" for v, x in sorted(per_view.items())))
for k, r in sorted(res.items(), key=lambda kv: -kv[1]["body"])[:10]:
    print(f"  {k:40s} {r['body']:.2f}%  (through {r['through']:.2f}, opening {r['opening']:.2f})")
T, cols = 200, 8
try:
    font = ImageFont.truetype("arial.ttf", 12)
except OSError:
    font = ImageFont.load_default()
rows = -(-len(tiles) // cols)
sheet = Image.new("RGB", (T * cols, (T + 16) * rows + 26), (25, 25, 28))
d = ImageDraw.Draw(sheet)
d.text((4, 4), f"his body showing (head excluded): mean {mean['body']:.2f}% of the figure, {len(res)} images — "
       f"red = poking through the armour {mean['through']:.2f}%, blue = at an opening / hole {mean['opening']:.2f}%",
       fill=(235, 235, 235), font=font)
for i, (k, im, r) in enumerate(tiles):
    x, y = (i % cols) * T, 26 + (i // cols) * (T + 16)
    sheet.paste(im.resize((T, T), Image.NEAREST), (x, y + 16))
    d.text((x + 3, y + 1), f"{k.split('/')[-1]} {r['body']:.2f}%", fill=(235, 235, 235), font=font)
sheet.save(OUT)
if JSON_OUT:
    json.dump({"mean_pct": {k: round(v, 3) for k, v in mean.items()},
               "per_view": {v: round(float(np.mean(x)), 3) for v, x in per_view.items()}, "per_image": res},
              open(JSON_OUT, "w"), indent=1)
print("SKIN_METRIC_OK", OUT)
