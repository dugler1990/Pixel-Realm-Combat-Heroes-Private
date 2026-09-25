"""Render every action in an animated .blend to PNG frames (two camera angles side by side).

    .venv-bpy/Scripts/python.exe anim_video.py <animated.blend> <out_dir> [px] [step]

Then `python make_mp4.py <out_dir>` turns each action's folder into an mp4 (cv2 is not in
.venv-bpy, bpy is not in the cv2 venv, hence the two steps). Stills cannot show timing; an
attack is all timing.
"""
import math
import os
import sys

import bpy
from mathutils import Vector
from PIL import Image, ImageDraw

BLEND = os.path.abspath(sys.argv[1])
OUT = os.path.abspath(sys.argv[2])
PX = int(sys.argv[3]) if len(sys.argv) > 3 else 320
STEP = int(sys.argv[4]) if len(sys.argv) > 4 else 2
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=BLEND)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
sc = bpy.context.scene

for s in mesh.material_slots:                       # the metallic map renders him almost black
    nt = s.material.node_tree
    b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    for l in list(b.inputs["Metallic"].links):
        nt.links.remove(l)
    b.inputs["Metallic"].default_value = 0

sc.render.engine = "BLENDER_EEVEE_NEXT"
sc.eevee.taa_render_samples = 8
sc.render.film_transparent = False
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
cam.data.ortho_scale = H * 1.35                     # frame him, not the empty room

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

tmp = os.path.join(OUT, "_f.png")


def shot(yaw_deg):
    a = math.radians(yaw_deg)
    cam.location = (4 * math.sin(a), -4 * math.cos(a), MID)
    cam.rotation_euler = (math.radians(90), 0, a)
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    return Image.open(tmp).convert("RGB")


ad = arm.animation_data
for name in sorted(a.name for a in bpy.data.actions):
    act = bpy.data.actions[name]
    ad.action = act
    if hasattr(act, "slots") and hasattr(ad, "action_slot") and len(act.slots):
        ad.action_slot = act.slots[0]
    n0, n1 = int(act.frame_start), int(act.frame_end)
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    for i, f in enumerate(range(n0, n1 + 1, STEP)):
        sc.frame_set(f)
        pair = Image.new("RGB", (PX * 2, PX))
        pair.paste(shot(25), (0, 0))
        pair.paste(shot(90), (PX, 0))
        dr = ImageDraw.Draw(pair)
        dr.text((9, 9), f"{name}  {f}/{n1}", fill=(0, 0, 0))
        dr.text((8, 8), f"{name}  {f}/{n1}", fill=(255, 230, 80))
        dr.text((PX + 8, 8), "side", fill=(160, 220, 160))
        pair.save(os.path.join(d, "%04d.png" % i))
    print("frames", name, len(range(n0, n1 + 1, STEP)), flush=True)
    ad.action = None
if os.path.exists(tmp):
    os.remove(tmp)
print("FRAMES_OK", OUT)
