"""Does a Corrective Smooth modifier fix the armpit collapse? Measure, then show.

    .venv-bpy/Scripts/python.exe smooth_test.py <animated.blend> <action> <frame> <out.png>

Renders the same frame at several modifier settings and prints the edge-stretch percentiles
for each, so the choice is made on numbers rather than on how the thumbnail looks.
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw

BLEND, ACTION, FRAME, OUT = sys.argv[1], sys.argv[2], int(sys.argv[3]), os.path.abspath(sys.argv[4])
PX = 560
# (factor, iterations, smooth_type) - None means no modifier at all
SETTINGS = [None, (0.5, 12, "SIMPLE"), (1.0, 25, "SIMPLE"), (1.0, 40, "LENGTH_WEIGHTED")]

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
a = math.radians(25)
cam.location = (4 * math.sin(a), -4 * math.cos(a), MID)
cam.rotation_euler = (math.radians(90), 0, a)
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
rl = np.linalg.norm(rest[ev[:, 0]] - rest[ev[:, 1]], axis=1)
ok = rl > 1e-7


def stretch():
    dg = bpy.context.evaluated_depsgraph_get()
    eo = mesh.evaluated_get(dg)
    tm = eo.to_mesh()
    p = np.empty(len(tm.vertices) * 3, np.float64)
    tm.vertices.foreach_get("co", p)
    p = p.reshape(-1, 3)
    eo.to_mesh_clear()
    pl = np.linalg.norm(p[ev[:, 0]] - p[ev[:, 1]], axis=1)
    r = np.ones_like(rl)
    r[ok] = pl[ok] / rl[ok]
    return np.percentile(r, 99), np.percentile(r, 99.9), int((r > 3).sum())


tiles = []
tmp = os.path.join(os.path.dirname(OUT), "_c.png")
for cfg in SETTINGS:
    for m in [m for m in mesh.modifiers if m.type == "CORRECTIVE_SMOOTH"]:
        mesh.modifiers.remove(m)
    if cfg:
        f, it, st = cfg
        m = mesh.modifiers.new("cs", "CORRECTIVE_SMOOTH")
        m.factor, m.iterations, m.smooth_type = f, it, st
        m.use_only_smooth = False
        label = "factor %.1f  iter %d  %s" % (f, it, st.lower())
    else:
        label = "no smoothing"
    bpy.context.view_layer.update()
    p99, p999, n3 = stretch()
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    img = Image.open(tmp).convert("RGB")
    d = ImageDraw.Draw(img)
    txt = "%s\np99 %.2fx  p99.9 %.2fx  >3x: %d" % (label, p99, p999, n3)
    d.multiline_text((9, 9), txt, fill=(0, 0, 0))
    d.multiline_text((8, 8), txt, fill=(255, 230, 80))
    tiles.append(img)
    print("%-34s p99 %6.2f  p99.9 %7.2f  verts>3x %6d" % (label, p99, p999, n3), flush=True)

sheet = Image.new("RGB", (PX * len(tiles), PX))
for i, t in enumerate(tiles):
    sheet.paste(t, (i * PX, 0))
sheet.save(OUT)
os.remove(tmp)
print("SMOOTH_TEST", OUT, flush=True)
