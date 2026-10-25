"""One labelled reel from a folder of Kimodo cells. `cell_reel.py <cells_dir> <out_dir>`

Writes per-cell PNG frames with the cell name, its duration/constraint, and its scores burned
in; make_mp4 then turns each into a clip and the whole lot into one reel. Raw BVH only.
"""
import glob
import json
import os
import re
import sys
import textwrap

import bpy
import numpy as np
from PIL import Image, ImageDraw

# under `blender -b --python x.py -- a b c` sys.argv still holds blender's own flags,
# so read the arguments after the "--" separator, not from position 1.
ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SRC, OUT = (os.path.abspath(p) for p in ARGV[0:2])
MANIFEST = json.load(open(ARGV[2])) if len(ARGV) > 2 else {}
PAT = re.compile(ARGV[3]) if len(ARGV) > 3 else None   # one reel per block
os.makedirs(OUT, exist_ok=True)
PX = 420
HDR = 132        # header: cell name, scores, params, wrapped prompt


def metrics(path):
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
        if m2 and cur:
            names.append(cur); chans.append(m2.group(2).split()); cur = None
        if s.startswith("Frame Time"):
            seen = True
    A = np.array(rows)
    off, k = {}, 0
    for n, cs in zip(names, chans):
        off[n] = {c: k + i for i, c in enumerate(cs)}
        k += len(cs)
    rc = [i for j in off.values() for c, i in j.items() if c.endswith("rotation")]
    R = np.degrees(np.unwrap(np.radians(A[:, rc]), axis=0))
    step = np.abs(np.diff(R, axis=0)).sum(axis=1)
    hipj = off.get("Hips") or list(off.values())[0]
    hy = hipj.get("Yposition")
    return len(A), ((float(np.ptp(A[:, hy])) / 100.0) if hy is not None else 0.0), float(step.max())


idx = 0
for d in sorted(glob.glob(os.path.join(SRC, "*"))):
    fs = sorted(glob.glob(os.path.join(d, "**", "*.bvh"), recursive=True)) if os.path.isdir(d) else []
    if not fs:
        continue
    name = os.path.basename(d)
    if PAT is not None and not PAT.match(name):
        continue
    nfr, hip, peak = metrics(fs[0])
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_anim.bvh(filepath=fs[0], global_scale=0.01, rotate_mode="NATIVE")
    src = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
    act = src.animation_data.action
    f0, f1 = (int(round(x)) for x in act.frame_range)
    sc = bpy.context.scene
    pts = []
    for fr in range(f0, f1 + 1, max((f1 - f0) // 25, 1)):
        sc.frame_set(fr); bpy.context.view_layer.update()
        pts += [src.matrix_world @ pb.head for pb in src.pose.bones]
    P = np.array([[v.x, v.y, v.z] for v in pts])
    zlo, zhi, cx = P[:, 2].min(), P[:, 2].max(), P[:, 0].mean()
    k = PX * 0.72 / max(zhi - zlo, 1e-6)
    dd = os.path.join(OUT, "%03d_%s" % (idx, name))
    os.makedirs(dd, exist_ok=True)
    meta = MANIFEST.get(name, {})
    verdict = "DEAD" if (hip < 0.05 and peak < 60) else ("weak" if peak < 120 else "MOVES")
    for i, fr in enumerate(range(f0, f1 + 1, 2)):
        sc.frame_set(fr); bpy.context.view_layer.update()
        im = Image.new("RGB", (PX, PX + HDR), (17, 17, 23))
        dr = ImageDraw.Draw(im)
        for pb in src.pose.bones:
            h, t = src.matrix_world @ pb.head, src.matrix_world @ pb.tail
            lo = pb.name.lower()
            col = ((90, 200, 255) if lo.startswith("left") else
                   (255, 170, 80) if lo.startswith("right") else (225, 225, 225))
            dr.line([(PX * .5 + (h.x - cx) * k, HDR + PX * .88 - (h.z - zlo) * k),
                     (PX * .5 + (t.x - cx) * k, HDR + PX * .88 - (t.z - zlo) * k)],
                    fill=col, width=2)
        dr.text((9, 8), "%03d  %s" % (idx, name[:44]), fill=(255, 225, 70))
        dr.text((9, 27), "%d frm   hip %.2f   peak %.0f   %s" % (nfr, hip, peak, verdict),
                fill=(140, 220, 255))
        dr.text((9, 45), meta.get("params", "")[:70], fill=(255, 190, 110))
        for li, ln in enumerate(textwrap.wrap(meta.get("prompt", ""), 66)[:4]):
            dr.text((9, 63 + li * 16), ln, fill=(190, 190, 190))
        im.save(os.path.join(dd, "%04d.png" % i))
    print("reel %03d %-40s hip %6.2f peak %5.0f %s" % (idx, name[:40], hip, peak, verdict),
          flush=True)
    idx += 1
print("CELLS", idx, OUT, flush=True)
