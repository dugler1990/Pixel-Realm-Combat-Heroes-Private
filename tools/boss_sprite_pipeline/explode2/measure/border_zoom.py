"""Close-ups of the borders between pieces, for two or more cuts side by side.

    .venv-bpy/Scripts/python.exe border_zoom.py <out.png> <label>=<cut_dir> [<label>=<cut_dir> ...] [--pairs a|b,c|d]

Each cut_dir: labels_face.npy + parts.json + cams.json (its "glb" is the mesh the labels belong to).
For each pair of parts (default: torso|arm_l, torso|pauldron_l, torso|belt, belt|skirt, arm_r|gauntlet_r,
skirt|leg_l) the camera looks at where they meet in the LAST cut, from outside, zoomed to 18 % of his
height. Rows = pairs, columns = cuts, faces in part colours (the same colour per part name in every cut).
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

argv = sys.argv[1:]
PAIRS = ["torso|arm_l", "torso|pauldron_l", "torso|belt", "belt|skirt", "arm_r|gauntlet_r", "skirt|leg_l"]
if "--pairs" in argv:
    i = argv.index("--pairs")
    PAIRS = argv[i + 1].split(",")
    del argv[i:i + 2]
# --pose <posed_verts.npy>: show the cut on the posed mesh (explode_render --pose), e.g. arms raised, so the
# plate's side under the arm - hidden at rest - is in view
POSED = None
if "--pose" in argv:
    i = argv.index("--pose")
    POSED = os.path.abspath(argv[i + 1])
    del argv[i:i + 2]
OUT = os.path.abspath(argv[0])
CUTS = [(a.split("=", 1)[0], os.path.abspath(a.split("=", 1)[1])) for a in argv[1:]]
PALETTE = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
           (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (220, 190, 255),
           (170, 110, 40), (255, 250, 200), (128, 0, 0), (170, 255, 195)]
T = 420

glb = json.load(open(os.path.join(CUTS[-1][1], "cams.json")))["glb"]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
mesh = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not mesh]:
    bpy.data.objects.remove(o, do_unlink=True)
me = mesh.data
co = np.empty(len(me.vertices) * 3, np.float32)
me.vertices.foreach_get("co", co)
m = np.array(mesh.matrix_world)
V = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
if POSED:
    V = np.load(POSED).astype(np.float64)
    mi = np.linalg.inv(m)
    me.vertices.foreach_set("co", (V @ mi[:3, :3].T + mi[:3, 3]).astype(np.float32).ravel())
    me.update()
F = np.empty(len(me.polygons) * 3, np.int64)
me.polygons.foreach_get("vertices", F)
F = F.reshape(-1, 3)
h = float(np.ptp(V[:, 2]))
cen = V[F].mean(1)
axis_xy = (V[:, :2].min(0) + V[:, :2].max(0)) / 2

cuts = []
for label, d in CUTS:
    names = json.load(open(os.path.join(d, "parts.json")))["parts"]
    lab = np.load(os.path.join(d, "labels_face.npy"))
    assert len(lab) == len(F), f"{d}: labels do not match the mesh"
    cuts.append((label, np.array(names, dtype=object)[lab]))
all_names = sorted({n for _, nm in cuts for n in set(nm.tolist())})
colour_of = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(all_names)}

sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"
sc.display.shading.color_type = "VERTEX"
sc.render.resolution_x = sc.render.resolution_y = T
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.18, 0.18, 0.2)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = 0.18 * h
attr = me.color_attributes.new("part", "BYTE_COLOR", "CORNER")
loop_face = np.repeat(np.arange(len(F)), 3)

# where each pair meets, in the last cut: faces of a within 0.4 % h of a face of b
spots = []
names_last = cuts[-1][1]
for pr in PAIRS:
    a, b = pr.split("|")
    fa, fb = np.nonzero(names_last == a)[0], np.nonzero(names_last == b)[0]
    if not len(fa) or not len(fb):
        spots.append(None)
        continue
    dist, _ = cKDTree(cen[fb]).query(cen[fa], workers=-1)
    near = fa[dist < 0.004 * h]
    if not len(near):
        spots.append(None)
        continue
    c = np.median(cen[near], 0)
    out = np.r_[c[:2] - axis_xy, 0.0]
    out = out / max(np.linalg.norm(out), 1e-9)
    spots.append((Vector(c.tolist()), Vector((out + np.array([0, -0.35, 0.25])).tolist()).normalized()))

try:
    font = ImageFont.truetype("arial.ttf", 18)
except OSError:
    font = ImageFont.load_default()
LAB = 26
sheet = Image.new("RGB", (T * len(cuts), (T + LAB) * len(PAIRS)), (25, 25, 28))
draw = ImageDraw.Draw(sheet)
tmp = os.path.splitext(OUT)[0] + "_tmp.png"
for c_i, (label, nm) in enumerate(cuts):
    rgb = np.array([colour_of[n] for n in nm], np.float32) / 255
    attr.data.foreach_set("color", np.c_[rgb[loop_face], np.ones(len(loop_face))].astype(np.float32).ravel())
    me.update()
    for r, (pr, spot) in enumerate(zip(PAIRS, spots)):
        draw.text((c_i * T + 6, r * (T + LAB) + 4), f"{label} | {pr}", fill=(235, 235, 235), font=font)
        if spot is None:
            continue
        c, d = spot
        cam.location = c + d * h
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = tmp
        bpy.ops.render.render(write_still=True)
        sheet.paste(Image.open(tmp).convert("RGB"), (c_i * T, r * (T + LAB) + LAB))
os.remove(tmp)
sheet.save(OUT)
print("BORDER_ZOOM_OK", OUT)
