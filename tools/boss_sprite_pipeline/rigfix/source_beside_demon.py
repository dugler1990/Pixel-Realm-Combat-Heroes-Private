"""Pair already-rendered demon frames with a drawn source skeleton. No GPU, no re-render.

    .venv-bpy/Scripts/python.exe source_beside_demon.py <bvh_dir> <video_dir> <out_dir> [step]

`source_vs_demon.py` re-rendered the demon to sit beside the source, which cost two Eevee
renders per frame and ran at minutes per clip. The demon frames already exist from the normal
video pass, and drawing a stick figure is free - so read the BVH, draw the source at matching
frames, and paste the existing render next to it.

Layout per frame: SOURCE front | SOURCE side | DEMON front+side (the demon panel is the
existing two-angle render, used as-is).
"""
import glob
import math
import os
import sys

import bpy
import numpy as np
from PIL import Image, ImageDraw

BVH_DIR, VID_DIR, OUT = (os.path.abspath(p) for p in sys.argv[1:4])
STEP = int(sys.argv[4]) if len(sys.argv) > 4 else 3
YAWS = (25, 90)
os.makedirs(OUT, exist_ok=True)

for bvh in sorted(glob.glob(os.path.join(BVH_DIR, "*.bvh"))):
    clip = os.path.splitext(os.path.basename(bvh))[0]
    frames = sorted(glob.glob(os.path.join(VID_DIR, clip, "*.png")))
    if not frames:
        print("skip", clip, "(no rendered frames)", flush=True)
        continue
    demo = Image.open(frames[0])
    PX = demo.size[1]                      # the demon panel is 2*PX wide, PX tall

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_anim.bvh(filepath=bvh, global_scale=0.01, rotate_mode="NATIVE")
    src = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
    act = src.animation_data.action
    f0, f1 = (int(round(x)) for x in act.frame_range)
    sc = bpy.context.scene

    d = os.path.join(OUT, clip)
    os.makedirs(d, exist_ok=True)
    for i, path in enumerate(frames):
        fr = min(f0 + i * STEP, f1)
        sc.frame_set(fr)
        bpy.context.view_layer.update()
        P = {pb.name: (src.matrix_world @ pb.head, src.matrix_world @ pb.tail)
             for pb in src.pose.bones}
        allp = np.array([[v.x, v.y, v.z] for hw in P.values() for v in hw])
        hgt = max(allp[:, 2].max() - allp[:, 2].min(), 1e-6)
        cz = (allp[:, 2].max() + allp[:, 2].min()) * 0.5

        panels = []
        for yaw in YAWS:
            a = math.radians(yaw)
            c, sn = math.cos(a), math.sin(a)
            k = PX * 0.62 / hgt
            cx = (allp[:, 0] * c + allp[:, 1] * sn).mean()
            im = Image.new("RGB", (PX, PX), (20, 20, 26))
            dr = ImageDraw.Draw(im)

            def put(v):
                return (PX * 0.5 + (v.x * c + v.y * sn - cx) * k, PX * 0.5 - (v.z - cz) * k)

            for nm, (hh, tt) in P.items():
                lo = nm.lower()
                col = ((90, 200, 255) if lo.startswith("left") else
                       (255, 170, 80) if lo.startswith("right") else (225, 225, 225))
                dr.line([put(hh), put(tt)], fill=col, width=3)
            tag = "SOURCE " + ("front" if yaw == YAWS[0] else "side")
            dr.text((9, 9), tag, fill=(0, 0, 0))
            dr.text((8, 8), tag, fill=(120, 240, 255))
            panels.append(im)

        dem = Image.open(path).convert("RGB")
        sheet = Image.new("RGB", (PX * 2 + dem.size[0], PX))
        sheet.paste(panels[0], (0, 0))
        sheet.paste(panels[1], (PX, 0))
        sheet.paste(dem, (PX * 2, 0))
        ds = ImageDraw.Draw(sheet)
        lab = "%s  f%d" % (clip, fr)
        ds.text((PX * 2 + 9, PX - 26), lab, fill=(0, 0, 0))
        ds.text((PX * 2 + 8, PX - 27), lab, fill=(255, 230, 80))
        sheet.save(os.path.join(d, "%04d.png" % i))
    print("paired", clip, len(frames), "frames", flush=True)

print("PAIR_OK", OUT, flush=True)
