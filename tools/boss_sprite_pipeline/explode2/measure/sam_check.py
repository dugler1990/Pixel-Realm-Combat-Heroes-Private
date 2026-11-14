"""What SAM itself says on single views, before any combining: is a bad cut SAM's fault or the merge's?

    python sam_check.py <views_dir> <out.png> [cam ...]

For each camera (default: the upper and lower crops nearest yaw 0 / 90 / 180 / 270 at low elevation),
every pixel takes the part whose mask covers it with the highest score x priority, exactly the rules
explode_label.py votes with (PROMPT_PART, SKIP, MIN_INSTANCE, PRIORITY), drawn over the lit render.
Pixels no mask covers stay uncoloured. Compare with the cut (PARTS_SHEET.png): where this is clean and
the cut is not, the combining is at fault, not SAM.
"""
import ast
import glob
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
WORK, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])

# the labeller's own rules, read from its source so the two cannot drift apart
src = open(os.path.join(HERE, "..", "..", "explode", "explode_label.py"), encoding="utf-8").read()
tree = ast.parse(src)
RULES = {}
for node in tree.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and \
            node.targets[0].id in ("PROMPT_PART", "SKIP", "MIN_INSTANCE", "PRIORITY"):
        RULES[node.targets[0].id] = ast.literal_eval(node.value)
PARTS = sorted(set(RULES["PROMPT_PART"].values()))
PALETTE = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
           (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (220, 190, 255),
           (170, 110, 40), (255, 250, 200)]
cams = json.load(open(os.path.join(WORK, "cams.json")))["cams"]
if len(sys.argv) > 3:
    pick = [c for c in cams if c["name"] in sys.argv[3:]]
else:
    pick = []
    for yaw in (0, 90, 180, -90):
        low = [c for c in cams if abs(c["elev"]) < 25 and c["crop"] in ("upper", "lower")]
        best = min(low, key=lambda c: abs((c["yaw"] - yaw + 180) % 360 - 180))
        pick += [c for c in low if c["name"].split("_")[0] == best["name"].split("_")[0]]
try:
    font = ImageFont.truetype("arial.ttf", 18)
except OSError:
    font = ImageFont.load_default()
T = 560
tiles = []
for c in pick:
    rgba = Image.open(os.path.join(WORK, c["name"] + "_lit.png")).convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (110, 110, 110, 255))
    bg.alpha_composite(rgba)
    img = np.asarray(bg.convert("RGB")).astype(np.float32)
    best = np.zeros(img.shape[:2], np.float32)
    lab = np.full(img.shape[:2], -1)
    for f in glob.glob(os.path.join(WORK, "masks", c["name"] + "__*.png")):
        _, prompt, k, score = os.path.basename(f)[:-4].split("__")
        part = RULES["PROMPT_PART"].get(prompt)
        if part is None or (c["crop"], prompt) in RULES["SKIP"] or float(score) < RULES["MIN_INSTANCE"]:
            continue
        m = np.asarray(Image.open(f).convert("L")) > 127
        v = float(score) * RULES["PRIORITY"][part]
        win = m & (v > best)
        best[win], lab[win] = v, PARTS.index(part)
    out = img.copy()
    for j in range(len(PARTS)):
        sel = lab == j
        out[sel] = img[sel] * 0.35 + np.array(PALETTE[j]) * 0.65
    t = Image.fromarray(out.astype(np.uint8)).resize((T, T))
    ImageDraw.Draw(t).text((6, 4), c["name"], fill=(255, 255, 255), font=font)
    tiles.append(t)
cols = 2
sheet = Image.new("RGB", (T * cols + 220, T * ((len(tiles) + 1) // cols)), (25, 25, 28))
for i, t in enumerate(tiles):
    sheet.paste(t, (T * (i % cols), T * (i // cols)))
d = ImageDraw.Draw(sheet)
for j, p in enumerate(PARTS):
    d.rectangle((T * cols + 10, 10 + 26 * j, T * cols + 28, 28 + 26 * j), fill=PALETTE[j])
    d.text((T * cols + 36, 10 + 26 * j), p, fill=(235, 235, 235), font=font)
sheet.save(OUT)
print("SAM_CHECK_OK", OUT, [c["name"] for c in pick])
