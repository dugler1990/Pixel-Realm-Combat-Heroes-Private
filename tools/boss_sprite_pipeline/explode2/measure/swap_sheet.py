"""Swap test sheet: the same poses without and with the worn pieces, side by side.

    python swap_sheet.py <out.png> <label>=<frames_dir> [<label>=<frames_dir> ...]

frames_dir: an explode_pose.py _frames_* folder (one <pose>_<view>.png per pose and view). One row per
key pose, one column per folder, labelled.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.abspath(sys.argv[1])
COLS = [(a.split("=", 1)[0], os.path.abspath(a.split("=", 1)[1])) for a in sys.argv[2:]]
KEY = ["rest_front", "rest_34", "rest_back", "arms_up_front", "arms_up_34", "arms_fwd_side", "twist_34",
       "bend_side", "step_side"]
try:
    font = ImageFont.truetype("arial.ttf", 20)
except OSError:
    font = ImageFont.load_default()
first = Image.open(os.path.join(COLS[0][1], KEY[0] + ".png"))
T, LAB = first.width, 30
sheet = Image.new("RGB", (T * len(COLS), (T + LAB) * len(KEY)), (25, 25, 28))
d = ImageDraw.Draw(sheet)
for r, k in enumerate(KEY):
    for c, (label, folder) in enumerate(COLS):
        p = os.path.join(folder, k + ".png")
        if os.path.isfile(p):
            sheet.paste(Image.open(p).convert("RGB"), (c * T, r * (T + LAB) + LAB))
        d.text((c * T + 8, r * (T + LAB) + 5), f"{label} | {k.replace('_', ' ')}", fill=(235, 235, 235), font=font)
sheet.save(OUT)
print("SWAP_SHEET_OK", OUT)
