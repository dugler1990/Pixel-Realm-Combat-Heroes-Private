"""Render the rigged base body's silhouette (dark on white, orthographic, 1024²) from the front / back / sides, as
the bare reference for outline_check.py when a concept view has no bare counterpart (e.g. the armour's back view).

    .venv-bpy/Scripts/python.exe body_silhouette.py <base_rigged.glb> <out_dir> [front back left right]

Figure faces -y. 'back' looks from +y (his left on the image's left), 'left' = his left side.
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

BASE, OUT = sys.argv[1], os.path.abspath(sys.argv[2])     # Blender resolves a relative render path elsewhere
VIEWS = sys.argv[3:] or ["front", "back"]
AZ = {"front": 0, "back": 180, "left": 90, "right": -90}
os.makedirs(OUT, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=BASE)
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not body]:
    bpy.data.objects.remove(o, do_unlink=True)
m = np.array(body.matrix_world)
co = np.array([v.co[:] for v in body.data.vertices]) @ m[:3, :3].T + m[:3, 3]
h = float(np.ptp(co[:, 2]))
centre = Vector(((co.min(0) + co.max(0)) / 2).tolist())
sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "FLAT"
sc.display.shading.color_type = "OBJECT"
body.color = (0.1, 0.1, 0.1, 1)
sc.view_settings.view_transform = "Standard"
sc.world = bpy.data.worlds.new("w")
sc.world.color = (1, 1, 1)
sc.render.resolution_x = sc.render.resolution_y = 1024
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = h * 1.04
for v in VIEWS:
    a = math.radians(AZ[v])
    d = Vector((-math.sin(a), -math.cos(a), 0))
    cam.location = centre + d * h * 3
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = os.path.join(OUT, f"body_{v}.png")
    bpy.ops.render.render(write_still=True)
    print("WROTE", sc.render.filepath)
