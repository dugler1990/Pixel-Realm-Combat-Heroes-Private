"""Show how explode_merge decides what of HoloPart's piece to keep, on one part.

    .venv-bpy/Scripts/python.exe merge_explain.py <cut_dir> <holopart_output.glb> <part> <out.png>

explode_merge keeps a HoloPart face only if its centre is farther than KEEP_FROM_SHELL (0.6 % of height)
from the cut shell, or its nearest shell vertex lies on the shell's cut edge. Top row: the cut shell (grey),
HoloPart's piece coloured kept (green) / dropped (red), the merged piece (shell + kept). Bottom: a slice
through the part's middle (the cut shell black, HoloPart kept green / dropped red) with the threshold
drawn as a scale bar, so the plate's thickness can be compared with it.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw, ImageFont
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "explode"))
from explode_common import match_by_centre, world_verts  # noqa: E402

CUT, RAW, PART, OUT = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3], os.path.abspath(sys.argv[4])
KEEP_FROM_SHELL = 0.006
h = json.load(open(os.path.join(CUT, "cams.json")))["height"]

bpy.ops.wm.read_factory_settings(use_empty=True)


def load(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    objs = {}
    for o in [o for o in bpy.data.objects if o not in before]:
        if o.type == "MESH":
            objs[o.name.split(".")[0]] = o
        else:
            bpy.data.objects.remove(o, do_unlink=True)
    return objs


def tris(o):
    me = o.data
    me.calc_loop_triangles()
    t = np.empty(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get("vertices", t)
    return world_verts(o), t.reshape(-1, 3)


shells = load(os.path.join(CUT, "shells_parts.glb"))
raw = match_by_centre(load(RAW), shells)
for n, o in list(shells.items()) + list(raw.items()):
    if n != PART:
        o.hide_render = True
VS, FS = tris(shells[PART])
VR, FR = tris(raw[PART])

# the merge rule, as explode_merge applies it
_, wid = np.unique(np.round(VS / (1e-6 * h)).astype(np.int64), axis=0, return_inverse=True)
wid = wid.ravel()
E = np.sort(wid[np.concatenate([FS[:, [0, 1]], FS[:, [1, 2]], FS[:, [2, 0]]])], axis=1)
ue, cnt = np.unique(E, axis=0, return_counts=True)
rim_w = np.zeros(wid.max() + 1, bool)
rim_w[ue[cnt == 1].ravel()] = True
rim = rim_w[wid]
cent = VR[FR].mean(1)
dist, near = cKDTree(VS).query(cent, workers=-1)
keep = (dist > KEEP_FROM_SHELL * h) | rim[near]
print(f"{PART}: HoloPart {len(FR)} faces, kept {int(keep.sum())} ({100 * keep.mean():.1f}%), "
      f"dropped {int((~keep).sum())}; median distance of dropped faces {np.median(dist[~keep]) / h * 100:.2f}% h", flush=True)

# --- renders --------------------------------------------------------------------------------
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"
sc.display.shading.color_type = "OBJECT"
sc.render.resolution_x = sc.render.resolution_y = 520
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.16, 0.16, 0.18)
shells[PART].hide_render = True
raw[PART].hide_render = True


def mesh_obj(name, V, F, colour):
    me = bpy.data.meshes.new(name)
    u, inv = np.unique(F, return_inverse=True)
    me.from_pydata(V[u].tolist(), [], inv.reshape(-1, 3).tolist())
    me.update()
    o = bpy.data.objects.new(name, me)
    sc.collection.objects.link(o)
    o.color = colour
    o.hide_render = True
    return o


grey, green, red = (0.75, 0.75, 0.75, 1), (0.1, 0.85, 0.2, 1), (0.95, 0.1, 0.1, 1)
o_shell = mesh_obj("shell", VS, FS, grey)
o_keep = mesh_obj("kept", VR, FR[keep], green)
o_drop = mesh_obj("dropped", VR, FR[~keep], red)
o_shell2 = mesh_obj("shell2", VS, FS, grey)
o_keep2 = mesh_obj("kept2", VR, FR[keep], green)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
c = Vector(((VS.min(0) + VS.max(0)) / 2).tolist())
size = float(np.ptp(VS, 0).max())
cam.data.ortho_scale = size * 1.25


def shot(objs, d, path):
    for o in (o_shell, o_keep, o_drop, o_shell2, o_keep2):
        o.hide_render = o not in objs
    d = Vector(d).normalized()
    cam.location = c + d * size * 3
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return Image.open(path).convert("RGB")


tmp = os.path.splitext(OUT)[0] + "_tmp"
os.makedirs(tmp, exist_ok=True)
VIEW = (0.35, -0.35, -0.87)          # from below, front-ish: the underside of a shoulder plate
tiles = [("cut shell (what SAM cut)", shot([o_shell], VIEW, os.path.join(tmp, "a.png"))),
         ("HoloPart: green kept / red dropped", shot([o_keep, o_drop], VIEW, os.path.join(tmp, "b.png"))),
         ("merged = shell + green", shot([o_shell2, o_keep2], VIEW, os.path.join(tmp, "c.png")))]

# --- slice through the middle ------------------------------------------------------------------
axis = int(np.argmax(np.ptp(VS, 0)))  # slice across the longest extent, through its middle
x0 = float((VS[:, axis].min() + VS[:, axis].max()) / 2)


def section(V, F):
    s = V[F][:, :, axis] - x0
    out = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        m = (s[:, a] * s[:, b]) < 0
        t = s[m, a] / (s[m, a] - s[m, b])
        out.append((m, V[F[m, a]] + t[:, None] * (V[F[m, b]] - V[F[m, a]])))
    segs = []
    pts = {}
    for m, p in out:
        for i, q in zip(np.nonzero(m)[0], p):
            pts.setdefault(i, []).append(q)
    for q in pts.values():
        if len(q) == 2:
            segs.append(q)
    return segs


others = [i for i in range(3) if i != axis]
S = 900
lo = VS[:, others].min(0) - 0.05 * size
span = float(np.ptp(VS[:, others], 0).max()) + 0.1 * size
img = Image.new("RGB", (S, S), (245, 245, 245))
d = ImageDraw.Draw(img)


def px(p):
    q = (p[others] - lo) / span
    return (q[0] * (S - 40) + 20, S - 20 - q[1] * (S - 40))


for segs, colour, w in ((section(VR, FR[~keep]), (230, 20, 20), 2), (section(VR, FR[keep]), (20, 170, 40), 2),
                        (section(VS, FS), (0, 0, 0), 2)):
    for a, b in segs:
        d.line([px(a), px(b)], fill=colour, width=w)
bar = KEEP_FROM_SHELL * h / span * (S - 40)
d.rectangle((30, 30, 30 + bar, 42), fill=(30, 90, 220))
try:
    font = ImageFont.truetype("arial.ttf", 20)
    small = ImageFont.truetype("arial.ttf", 16)
except OSError:
    font = small = ImageFont.load_default()
d.text((30, 48), f"blue bar = the merge's threshold, 0.6 % of height (~{KEEP_FROM_SHELL * 180:.1f} cm on a 1.8 m man)",
       fill=(30, 90, 220), font=small)
d.text((30, 70), "black = cut shell (one surface)   green = HoloPart kept   red = HoloPart dropped (closer than the bar)",
       fill=(40, 40, 40), font=small)

T = 520
sheet = Image.new("RGB", (max(3 * T, S), T + 34 + S + 34), (25, 25, 28))
dd = ImageDraw.Draw(sheet)
for i, (lab, t) in enumerate(tiles):
    sheet.paste(t, (i * T, 34))
    dd.text((i * T + 8, 7), lab, fill=(235, 235, 235), font=font)
dd.text((8, T + 41), f"slice through the middle of {PART}: kept {100 * keep.mean():.0f}% of HoloPart's faces", fill=(235, 235, 235), font=font)
sheet.paste(img, (0, T + 68))
sheet.save(OUT)
print("EXPLAIN_OK", OUT)
