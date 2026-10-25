"""Turn a folder of Kimodo cells into something reviewable: one numbered contact sheet plus a
labelled reel. Raw BVH only - no retarget, no demon, no render.

    block_report.py <cells_dir> <out_dir>

Each cell becomes one numbered row: 8 frames across the clip, the cell name, and its measured
hip range / hand excursion / peak. Scanning one image beats scrubbing sixty videos, and the row
numbers give a way to say "4 good, 9 dead" without naming files.
"""
import glob
import math
import os
import re
import sys

import bpy
import numpy as np
from PIL import Image, ImageDraw

# under `blender -b --python x.py -- a b c` sys.argv still holds blender's own flags,
# so read the arguments after the "--" separator, not from position 1.
ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SRC, OUT = (os.path.abspath(p) for p in ARGV[0:2])
# optional: only the cells whose name matches, so one runs folder gives one sheet per block
PAT = re.compile(ARGV[2]) if len(ARGV) > 2 else None
os.makedirs(OUT, exist_ok=True)
N, CELL = 8, 230


def bvh_metrics(path):
    """Channel offsets come from the CHANNELS declarations, not from assuming 6 per joint:
    the root carries 6 (position + rotation), every other joint usually 3."""
    names, chans, rows, seen, cur = [], [], [], False, None
    for line in open(path):
        s = line.strip()
        if seen:
            v = line.split()
            if v:
                rows.append([float(x) for x in v])
            continue
        m = re.match(r"(?:ROOT|JOINT)\s+(\S+)", s)
        if m:
            cur = m.group(1)
        m2 = re.match(r"CHANNELS\s+(\d+)\s+(.*)", s)
        if m2 and cur is not None:
            names.append(cur); chans.append(m2.group(2).split()); cur = None
        if s.startswith("Frame Time"):
            seen = True
    A = np.array(rows)
    if A.size == 0:
        return None
    off, k = {}, 0
    for n, cs in zip(names, chans):
        off[n] = {c: k + i for i, c in enumerate(cs)}
        k += len(cs)
    rot_cols = [i for j in off.values() for c, i in j.items() if c.endswith("rotation")]
    R = np.degrees(np.unwrap(np.radians(A[:, rot_cols]), axis=0))
    step = np.abs(np.diff(R, axis=0)).sum(axis=1)
    hipj = off.get("Hips") or off.get("Root") or list(off.values())[0]
    hy = hipj.get("Yposition")
    return dict(frames=len(A),
                hip=(float(np.ptp(A[:, hy])) / 100.0) if hy is not None else 0.0,  # cm -> m
                hand=0.0, peak=float(step.max()))


def draw(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_anim.bvh(filepath=path, global_scale=0.01, rotate_mode="NATIVE")
    src = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
    act = src.animation_data.action
    f0, f1 = (int(round(x)) for x in act.frame_range)
    sc = bpy.context.scene
    pts = []
    for fr in range(f0, f1 + 1, max((f1 - f0) // 20, 1)):
        sc.frame_set(fr)
        bpy.context.view_layer.update()
        pts += [src.matrix_world @ pb.head for pb in src.pose.bones]
    P = np.array([[v.x, v.y, v.z] for v in pts])
    zlo, zhi, cx = P[:, 2].min(), P[:, 2].max(), P[:, 0].mean()
    k = CELL * 0.78 / max(zhi - zlo, 1e-6)
    cells = []
    for i in range(N):
        sc.frame_set(f0 + int(i * (f1 - f0) / (N - 1)))
        bpy.context.view_layer.update()
        im = Image.new("RGB", (CELL, CELL), (17, 17, 23))
        dr = ImageDraw.Draw(im)
        for pb in src.pose.bones:
            h, t = src.matrix_world @ pb.head, src.matrix_world @ pb.tail
            lo = pb.name.lower()
            col = ((90, 200, 255) if lo.startswith("left") else
                   (255, 170, 80) if lo.startswith("right") else (225, 225, 225))
            dr.line([(CELL * .5 + (h.x - cx) * k, CELL * .88 - (h.z - zlo) * k),
                     (CELL * .5 + (t.x - cx) * k, CELL * .88 - (t.z - zlo) * k)],
                    fill=col, width=2)
        cells.append(im)
    return cells


cellsdirs = [d for d in sorted(glob.glob(os.path.join(SRC, "*")))
            if os.path.isdir(d) and (PAT is None or PAT.match(os.path.basename(d)))]
rows, reel = [], []
for i, d in enumerate(cellsdirs, 1):
    fs = sorted(glob.glob(os.path.join(d, "**", "*.bvh"), recursive=True))
    if not fs:
        continue
    m = bvh_metrics(fs[0])
    imgs = draw(fs[0])
    row = Image.new("RGB", (CELL * N + 430, CELL), (17, 17, 23))
    for j, im in enumerate(imgs):
        row.paste(im, (430 + j * CELL, 0))
    dr = ImageDraw.Draw(row)
    name = os.path.basename(d)
    verdict = ("DEAD" if m["hip"] < 0.05 and m["peak"] < 60 else
               "weak" if m["peak"] < 120 else "MOVES")
    dr.text((10, 12), "%2d  %s" % (i, name[:44]), fill=(255, 225, 70))
    dr.text((10, 40), "%d frames" % m["frames"], fill=(170, 170, 170))
    dr.text((10, 62), "hip  %.3f" % m["hip"], fill=(140, 220, 255))
    dr.text((10, 84), "hand %.3f" % m["hand"], fill=(140, 220, 255))
    dr.text((10, 106), "peak %.0f" % m["peak"], fill=(140, 220, 255))
    dr.text((10, 134), verdict, fill=((255, 90, 90) if verdict == "DEAD" else
                                      (255, 200, 80) if verdict == "weak" else (120, 255, 140)))
    rows.append(row)
    reel.append((i, name, verdict, m, imgs))
    print("row %2d  %-44s hip %.3f peak %5.0f  %s" % (i, name[:44], m["hip"], m["peak"], verdict),
          flush=True)

if rows:
    W, H = rows[0].size[0], rows[0].size[1]
    sheet = Image.new("RGB", (W, H * len(rows)))
    for i, r in enumerate(rows):
        sheet.paste(r, (0, i * H))
    p = os.path.join(OUT, "SHEET.png")
    sheet.save(p)
    print("SHEET", p, sheet.size, len(rows), "cells", flush=True)
