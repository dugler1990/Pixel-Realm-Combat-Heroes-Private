"""Render the posed frame and mark the torn vertices on it, so the tearing can be located.

    .venv-bpy/Scripts/python.exe stretch_map.py <animated.blend> <action> <frame> <out.png>
"""
import math
import os
import sys

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from PIL import Image, ImageDraw

BLEND, ACTION, FRAME, OUT = sys.argv[1], sys.argv[2], int(sys.argv[3]), os.path.abspath(sys.argv[4])
PX = 620

bpy.ops.wm.open_mainfile(filepath=os.path.abspath(BLEND))
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
sc = bpy.context.scene
ad = arm.animation_data
act = bpy.data.actions[ACTION]
ad.action = act
if hasattr(act, "slots") and hasattr(ad, "action_slot") and len(act.slots):
    ad.action_slot = act.slots[0]
sc.frame_set(FRAME)
bpy.context.view_layer.update()

for s in mesh.material_slots:
    nt = s.material.node_tree
    b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    for l in list(b.inputs["Metallic"].links):
        nt.links.remove(l)
    b.inputs["Metallic"].default_value = 0
sc.render.engine = "BLENDER_EEVEE_NEXT"
sc.eevee.taa_render_samples = 8
sc.render.resolution_x = sc.render.resolution_y = PX
sc.view_settings.view_transform = "Standard"
sc.render.image_settings.file_format = "PNG"
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
_vs = mesh.data.vertices
zs = [(mesh.matrix_world @ _vs[i].co).z for i in range(0, len(_vs), 37)]
H, MID = max(zs) - min(zs), (max(zs) + min(zs)) * 0.5
cam.data.ortho_scale = H * 1.35
for n, loc, e in (("k", (-2, -3, 3), 5.0), ("f", (3, -3, 1), 2.5), ("b", (0, 4, 2), 2.0)):
    L = bpy.data.lights.new(n, "SUN")
    L.energy = e
    o = bpy.data.objects.new(n, L)
    sc.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
w = bpy.data.worlds.new("w")
sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.25, 0.25, 0.28, 1)

nv = len(mesh.data.vertices)
rest = np.empty(nv * 3, np.float64)
mesh.data.vertices.foreach_get("co", rest)
rest = rest.reshape(-1, 3)
ne = len(mesh.data.edges)
ev = np.empty(ne * 2, np.int32)
mesh.data.edges.foreach_get("vertices", ev)
ev = ev.reshape(-1, 2)
dg = bpy.context.evaluated_depsgraph_get()
eo = mesh.evaluated_get(dg)
tm = eo.to_mesh()
posed = np.empty(len(tm.vertices) * 3, np.float64)
tm.vertices.foreach_get("co", posed)
posed = posed.reshape(-1, 3)
eo.to_mesh_clear()
rl = np.linalg.norm(rest[ev[:, 0]] - rest[ev[:, 1]], axis=1)
pl = np.linalg.norm(posed[ev[:, 0]] - posed[ev[:, 1]], axis=1)
ok = rl > 1e-7
ratio = np.ones_like(rl)
ratio[ok] = pl[ok] / rl[ok]

tiles = []
for yaw, thresh in ((25, 3.0), (25, 10.0), (110, 3.0)):
    a = math.radians(yaw)
    cam.location = (4 * math.sin(a), -4 * math.cos(a), MID)
    cam.rotation_euler = (math.radians(90), 0, a)
    tmp = os.path.join(os.path.dirname(OUT), "_s.png")
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    img = Image.open(tmp).convert("RGB")
    d = ImageDraw.Draw(img)
    bad = np.unique(ev[ratio > thresh].ravel())
    mw = mesh.matrix_world
    step = max(1, len(bad) // 6000)
    for i in bad[::step]:
        co = mw @ Vector(posed[int(i)])
        p = world_to_camera_view(sc, cam, co)
        if 0 <= p.x <= 1 and 0 <= p.y <= 1:
            x, y = p.x * PX, (1 - p.y) * PX
            d.ellipse([x - 1.6, y - 1.6, x + 1.6, y + 1.6], fill=(255, 40, 40))
    lbl = "%s f%d  yaw %d  stretch>%.0fx  (%d verts)" % (ACTION, FRAME, yaw, thresh, len(bad))
    d.text((9, 9), lbl, fill=(0, 0, 0))
    d.text((8, 8), lbl, fill=(255, 230, 80))
    tiles.append(img)
    print(lbl, flush=True)

sheet = Image.new("RGB", (PX * len(tiles), PX))
for i, t in enumerate(tiles):
    sheet.paste(t, (i * PX, 0))
sheet.save(OUT)
print("STRETCH_MAP", OUT, flush=True)
