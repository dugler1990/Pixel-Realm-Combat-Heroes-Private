"""Step 6: show HoloPart's completed parts next to the cut shells they came from.

    .venv-bpy/Scripts/python.exe explode_show.py <work_dir> <completed.glb> [body.glb]

Reads <work_dir>/input_parts.glb (step 3's shells) and the completed GLB (HoloPart output.glb, same
part names, same coordinates). Writes to <work_dir>:
  EXPLODED.png     completed parts pulled apart (front, 3/4), around body.glb in grey if given
  PARTS_ALONE.png  per part: shell vs completed, from the front-3/4 and the back-3/4
  completed.json   per part: faces and open (boundary) edges, shell vs completed
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw

from explode_common import match_by_centre, world_verts

WORK, DONE = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
BODY = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else None
PALETTE = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
           (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (220, 190, 255),
           (170, 110, 40), (255, 250, 200), (128, 0, 0), (170, 255, 195), (128, 128, 0), (255, 215, 180)]
TILE = 240


def log(*a):
    print(*a, flush=True)


def open_edges(o):
    """Boundary edges after welding coincident vertices: 0 = closed surface."""
    V = world_verts(o)
    tri = np.empty(len(o.data.polygons) * 3, np.int64)
    o.data.polygons.foreach_get("vertices", tri)   # imported glTF is all triangles
    h = float(np.ptp(V, 0).max())
    _, weld = np.unique(np.round(V / (1e-6 * h)).astype(np.int64), axis=0, return_inverse=True)
    F = weld.ravel()[tri.reshape(-1, 3)]
    E = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1)
    _, cnt = np.unique(E, axis=0, return_counts=True)
    return int((cnt == 1).sum()), len(F)


def load(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    objs = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    for o in objs:   # bake the import's node transforms so every object sits at its true place
        o.data.transform(o.matrix_world)
        o.parent = None
        o.matrix_world.identity()
    return objs


def part_name(o):
    return o.data.name.split(".")[0] if o.data.name else o.name.split(".")[0]


bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
shells = {part_name(o): o for o in load(os.path.join(WORK, "input_parts.glb"))}
done = {part_name(o): o for o in load(DONE)}
if not set(done) & set(shells):   # HoloPart's export renames parts geometry_<i>
    done = match_by_centre(done, shells, log)
names = [n for n in shells if n in done]
log("parts matched:", len(names), "| shell only:", sorted(set(shells) - set(done)), "| completed only:", sorted(set(done) - set(shells)))
body = load(BODY) if BODY else []
for o in body:
    o.color = (0.55, 0.55, 0.58, 1)

stats = {}
for j, n in enumerate(names):
    col = tuple(x / 255 for x in PALETTE[j % len(PALETTE)]) + (1,)
    shells[n].color = done[n].color = col
    (so, sf), (do, df) = open_edges(shells[n]), open_edges(done[n])
    stats[n] = {"shell_faces": sf, "shell_open_edges": so, "done_faces": df, "done_open_edges": do}
    log(f"{n:12s} shell {sf:7d} faces {so:6d} open edges | completed {df:7d} faces {do:6d} open edges")
json.dump(stats, open(os.path.join(WORK, "completed.json"), "w"), indent=1)

sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"
sc.display.shading.color_type = "OBJECT"
sc.render.film_transparent = False
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.2, 0.2, 0.22)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"


def shot(objs, yaw, path, res, elev=10, pad=1.15, centre=None, ortho=None):
    for o in bpy.data.objects:
        if o.type == "MESH":
            o.hide_render = o not in objs
    P = np.concatenate([world_verts(o) for o in objs])
    lo, hi = P.min(0), P.max(0)
    c = Vector(((lo + hi) / 2).tolist()) if centre is None else centre
    a, e = math.radians(yaw), math.radians(elev)
    d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
    cam.location = c + d * (3 * float(np.ptp(P, 0).max()) + 1)
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = ortho if ortho else pad * float(np.ptp(P, 0).max())
    cam.data.clip_end = 1000
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return Image.open(path).convert("RGB")


# --- each part alone: shell vs completed, front-3/4 and back-3/4 -------------------------------
tmp = os.path.join(WORK, "show_tmp")
os.makedirs(tmp, exist_ok=True)
per_row = 2
rows = math.ceil(len(names) / per_row)
sheet = Image.new("RGB", (TILE * 4 * per_row, rows * (TILE + 22) + 30), (30, 30, 34))
dr = ImageDraw.Draw(sheet)
for k in range(per_row):
    for i, t in enumerate(("shell 3/4", "done 3/4", "shell back", "done back")):
        dr.text((k * 4 * TILE + i * TILE + 6, 8), t, fill=(200, 200, 200))
for j, n in enumerate(names):
    r, k = divmod(j, per_row)
    x0, y0 = k * 4 * TILE, 30 + r * (TILE + 22)
    for i, (o, yaw) in enumerate(((shells[n], 35), (done[n], 35), (shells[n], 215), (done[n], 215))):
        im = shot([o], yaw, os.path.join(tmp, f"{n}_{i}.png"), TILE, elev=15)
        sheet.paste(im, (x0 + i * TILE, y0))
    s = stats[n]
    dr.text((x0 + 6, y0 + TILE + 4),
            f"{n}: shell {s['shell_faces']} f / {s['shell_open_edges']} open edges -> done {s['done_faces']} f / {s['done_open_edges']} open",
            fill=(240, 240, 240))
sheet.save(os.path.join(WORK, "PARTS_ALONE.png"))

# --- exploded: completed parts pulled away from the body centre --------------------------------
allP = np.concatenate([world_verts(shells[n]) for n in names])
h = float(np.ptp(allP[:, 2]))
body_c = (allP.min(0) + allP.max(0)) / 2
for n in names:
    o = done[n]
    c = world_verts(shells[n]).mean(0)
    off = (c - body_c) * np.array([0.9, 0.0, 0.55])
    if n.startswith("head"):
        off = np.array([0, 0, 0.12 * h])
    o.location = Vector(off.tolist())
bpy.context.view_layer.update()
objs =[done[n] for n in names] + body
ex = [shot(objs, y, os.path.join(tmp, f"exploded_{y:03d}.png"), 900, centre=Vector(body_c.tolist()), ortho=1.6 * h)
      for y in (0, 35)]
out = Image.new("RGB", (1800, 900))
out.paste(ex[0], (0, 0)); out.paste(ex[1], (900, 0))
out.save(os.path.join(WORK, "EXPLODED.png"))
log("SHOW_OK")
