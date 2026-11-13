"""The same clip without and with the worn pieces, frame by frame, one above the other.

    python anim_compare.py <out_dir> <clip> <label>=<explode_pose out dir> [<label>=<dir> ...]

Reads each dir's _anim_<clip>/<frame>.png (explode_pose.py --clips) and writes
<out_dir>/COMPARE_<clip>.gif (rows = labels) and COMPARE_<clip>.png (every 5th frame).
"""
import glob
import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT, CLIP = os.path.abspath(sys.argv[1]), sys.argv[2]
ROWS = [(a.split("=", 1)[0], os.path.abspath(a.split("=", 1)[1])) for a in sys.argv[3:]]
os.makedirs(OUT, exist_ok=True)
names = sorted(os.path.basename(p) for p in glob.glob(os.path.join(ROWS[0][1], f"_anim_{CLIP}", "[0-9][0-9][0-9][0-9].png")))
try:
    font = ImageFont.truetype("arial.ttf", 20)
except OSError:
    font = ImageFont.load_default()
frames = []
for n in names:
    ims = [Image.open(os.path.join(d, f"_anim_{CLIP}", n)).convert("RGB") for _, d in ROWS]
    W, H = ims[0].size
    fr = Image.new("RGB", (W, H * len(ims)))
    dr = ImageDraw.Draw(fr)
    for r, ((label, _), im) in enumerate(zip(ROWS, ims)):
        fr.paste(im, (0, r * H))
        dr.text((8, r * H + 6), f"{label} | {CLIP} frame {int(n[:4])}", fill=(255, 255, 255), font=font)
    frames.append(fr)
frames[0].save(os.path.join(OUT, f"COMPARE_{CLIP}.gif"), save_all=True, append_images=frames[1:], duration=100, loop=0)
pick = frames[::5]
W, H = pick[0].size
sheet = Image.new("RGB", (W // 2 * len(pick), H // 2))
for i, fr in enumerate(pick):
    sheet.paste(fr.resize((W // 2, H // 2)), (i * W // 2, 0))
sheet.save(os.path.join(OUT, f"COMPARE_{CLIP}.png"))
print("COMPARE_OK", os.path.join(OUT, f"COMPARE_{CLIP}.gif"), len(frames), "frames")
