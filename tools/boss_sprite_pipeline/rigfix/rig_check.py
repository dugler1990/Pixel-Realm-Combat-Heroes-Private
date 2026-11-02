"""How noisy are a rigged GLB's skin weights?

    .venv-bpy/Scripts/python.exe rig_check.py <rigged.glb> <roles.json> <out_dir>

Prints: weight jump between neighbouring vertices (L1 of the weight vectors over welded edges),
disagreement between UV-seam duplicates, influences per vertex. Renders the weights of the left
upper arm, chest and left thigh bones as heatmaps (front and back).
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image

GLB, ROLES, OUT = (os.path.abspath(a) for a in sys.argv[1:4])
os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
me = body.data
n = len(me.vertices)
co = np.empty(n * 3, np.float32)
me.vertices.foreach_get("co", co)
V = co.reshape(-1, 3) @ np.array(body.matrix_world)[:3, :3].T + np.array(body.matrix_world)[:3, 3]
h = float(np.ptp(V[:, 2]))
names = [g.name for g in body.vertex_groups]
W = np.zeros((n, len(names)), np.float32)
for v in me.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
nz = (W > 1e-3).sum(1)
print(f"{n} verts, {len(names)} bones; influences per vertex: mean {nz.mean():.2f}, max {nz.max()}, zero {int((nz == 0).sum())}")

_, wid = np.unique(np.round(V / (1e-6 * h)).astype(np.int64), axis=0, return_inverse=True)
wid = wid.ravel()
nW = wid.max() + 1
# UV-seam duplicates: do copies of the same point carry different weights?
rep = np.zeros(nW, np.int64)
rep[wid] = np.arange(n)
dup = np.abs(W - W[rep[wid]]).sum(1)
print(f"seam duplicates: {n - nW} extra copies; weight disagreement max {dup.max():.3f}, copies > 0.1: {int((dup > 0.1).sum())}")
e = np.empty(len(me.edges) * 2, np.int64)
me.edges.foreach_get("vertices", e)
e = e.reshape(-1, 2)
E = np.unique(np.sort(wid[e], 1), axis=0)
E = E[E[:, 0] != E[:, 1]]
WW = W[rep]
jump = np.abs(WW[E[:, 0]] - WW[E[:, 1]]).sum(1)
L = np.linalg.norm(V[rep[E[:, 0]]] - V[rep[E[:, 1]]], axis=1) / h
print(f"neighbour jump (L1, 0..2): median {np.median(jump):.3f}, p99 {np.percentile(jump, 99):.3f}, "
      f"edges > 0.3: {100 * (jump > 0.3).mean():.2f}%, > 0.6: {100 * (jump > 0.6).mean():.2f}%   (edge length median {np.median(L) * 100:.3f}% h)")

roles = json.load(open(ROLES))
show = {"upper arm L (" + roles["arm_l"]["shoulder"] + ")": roles["arm_l"]["shoulder"],
        "chest (" + roles["chest"] + ")": roles["chest"],
        "thigh L (" + roles["leg_l"]["hip"] + ")": roles["leg_l"]["hip"]}
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "VERTEX"
sc.render.resolution_x, sc.render.resolution_y = 700, 900
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.15, 0.15, 0.17)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
c = Vector(((V.min(0) + V.max(0)) / 2).tolist())
for o in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
    o.hide_render = True
lv = np.empty(len(me.loops), np.int64)
me.loops.foreach_get("vertex_index", lv)
attr = me.color_attributes.new("w", "BYTE_COLOR", "CORNER")
me.color_attributes.active_color = attr
tiles = []
for label, bone in show.items():
    w = W[:, names.index(bone)]
    rgb = np.stack([w, np.zeros_like(w), 1 - w], 1)          # blue 0 -> red 1
    rgb[w < 1e-3] = 0.25
    attr.data.foreach_set("color", np.c_[rgb[lv], np.ones(len(lv))].astype(np.float32).ravel())
    for yaw, zc, ortho in ((0, 0.72, 0.42), (180, 0.72, 0.42)):
        a = math.radians(yaw)
        d = Vector((math.sin(a), -math.cos(a), 0.05))
        target = Vector((c.x, c.y, V[:, 2].min() + zc * h)) if "thigh" not in label else Vector((c.x, c.y, V[:, 2].min() + 0.42 * h))
        cam.location = target + d * 3 * h
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        cam.data.ortho_scale = ortho * h * (900 / 700)
        p = os.path.join(OUT, f"w_{bone}_{yaw}.png")
        sc.render.filepath = p
        bpy.ops.render.render(write_still=True)
        tiles.append(Image.open(p).convert("RGB"))
    print("rendered", label)
sheet = Image.new("RGB", (700 * len(tiles), 900))
for i, t in enumerate(tiles):
    sheet.paste(t, (700 * i, 0))
sheet.save(os.path.join(OUT, "WEIGHTS.png"))
print("RIG_CHECK_OK")
