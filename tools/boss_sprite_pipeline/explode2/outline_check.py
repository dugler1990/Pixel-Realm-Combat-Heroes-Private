"""Does an armoured concept's outline contain the bare concept's outline, with room to spare?

    python outline_check.py <bare.png> <armoured.png> [...] [--margin 0.005] [--out <dir>]

Each image: the figure's silhouette (largest blob off the corner colour, holes filled), scaled to the bare
figure's height and lined up on the head top and the body centre. The head and neck (top 13 %) are left out: the
head stays bare. Bare skin that comes within --margin (x figure height) of the armour's edge, or crosses it, is a
fail pixel: plate must stand off the skin. Per image it prints the fail share of the bare outline, the widths per band
(% h) and writes OUTLINE_<name>.png: grey both, red bare body outside / too close to the armour, blue armour only.
The model that made an image is read from its file name.
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

argv = sys.argv[1:]
opt = {}
for f in ("--margin", "--out"):
    if f in argv:
        i = argv.index(f)
        opt[f] = argv[i + 1]
        del argv[i:i + 2]
MARGIN = float(opt.get("--margin", 0.005))
HEAD = 0.13
BANDS = [("shoulder", .80), ("chest", .72), ("waist", .60), ("hips", .52), ("thigh", .42), ("knee", .30),
         ("calf", .20), ("ankle", .08)]


def silhouette(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(int)
    m = np.abs(a - a[3, 3]).sum(2) > 40
    lab, _ = ndimage.label(m)
    m = lab == np.bincount(lab.ravel())[1:].argmax() + 1
    return ndimage.binary_fill_holes(m)


def normalise(m, H, size):
    """Scale to height H px, head top at row 20, body centre (mean x of the top 30 %) at the middle column."""
    ys, xs = np.nonzero(m)
    s = H / np.ptp(ys)
    top = ys.min()
    cx = xs[ys < top + 0.3 * np.ptp(ys)].mean()
    im = Image.fromarray((m * 255).astype(np.uint8))
    im = im.resize((round(m.shape[1] * s), round(m.shape[0] * s)), Image.NEAREST)
    out = Image.new("L", (size, size), 0)
    out.paste(im, (round(size / 2 - cx * s), round(20 - top * s)))
    return np.asarray(out) > 127


def widths(m, ys_bottom, H, f):
    y = int(ys_bottom - f * H)
    xs = np.nonzero(m[y])[0]
    if f < .5:                                   # one leg: the right half of the image
        xs = xs[xs > m.shape[1] // 2]
    return np.ptp(xs) / H * 100 if len(xs) else 0.0


bare_path, arm_paths = argv[0], argv[1:]
out_dir = opt.get("--out", os.path.dirname(os.path.abspath(arm_paths[0])))
b0 = silhouette(bare_path)
H = int(np.ptp(np.nonzero(b0)[0]))
SIZE = int(H * 1.15)
b = normalise(b0, H, SIZE)
yb = np.nonzero(b)[0]
body = b.copy()
body[: int(yb.min() + HEAD * H)] = False
grown = ndimage.binary_dilation(body, iterations=max(1, round(MARGIN * H)))
font = ImageFont.truetype("arial.ttf", 16)
print(f"bare {os.path.basename(bare_path)}: height {H} px, margin {MARGIN * 100:.1f} % h = {round(MARGIN * H)} px")
for p in arm_paths:
    a = normalise(silhouette(p), H, SIZE)
    fail = grown & ~a
    share = fail.sum() / body.sum() * 100
    name = os.path.splitext(os.path.basename(p))[0]
    print(f"\n{name}: bare body outside / within margin of the armour: {share:.2f} % of the bare outline")
    print("band       bare   armour  (% h)")
    for bn, f in BANDS:
        print(f"{bn:9s} {widths(b, yb.max(), H, f):5.1f}  {widths(a, yb.max(), H, f):5.1f}")
    im = np.zeros(b.shape + (3,), np.uint8)
    im[b & a] = (120, 120, 120)
    im[a & ~b] = (60, 140, 255)
    im[fail] = (255, 60, 40)
    pic = Image.fromarray(im)
    ImageDraw.Draw(pic).text((8, 8), f"{name}: fail {share:.2f} %", fill=(255, 255, 255), font=font)
    q = os.path.join(out_dir, f"OUTLINE_{name}.png")
    pic.save(q)
    print("wrote", q)
