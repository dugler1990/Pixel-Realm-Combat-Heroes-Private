"""Step 1: lit renders + world-position images of an outfit mesh, for SAM3 to label.

    .venv-bpy/Scripts/python.exe explode_render.py <outfit.glb> <work_dir> [8|96]

Cameras, each as two square crops (upper body, lower body) so hands and feet stay a usable size:
  8  (default) front / left / back / right (yaw 0, 90, 180, 270) at 10 deg elevation
  96 12 yaws (every 30 deg) x 4 elevations (-30 from below, 0, 25, 55 from above): reaches the
     armpits, inner thighs and shoulder tops the 8-view set never sees
Per camera writes <name>_lit.png (1120^2, texture + neutral light: SAM3 wants a lit render, see
NOTES_rig_jaw_sam3.md) and <name>_pos.exr (world xyz per pixel, alpha = coverage), plus cams.json.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

from explode_common import fill_unwritten_texels

GLB, WORK = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
VIEWSET = sys.argv[3] if len(sys.argv) > 3 else "8"
os.makedirs(WORK, exist_ok=True)
RES = 1120
CROPS = {"upper": (0.70, 0.66), "lower": (0.30, 0.62)}   # centre height (fraction of h), ortho (x h)
if VIEWSET == "8":
    VIEWS = [(v, yaw, 10) for v, yaw in (("front", 0), ("left", 90), ("back", 180), ("right", 270))]
else:
    VIEWS = [(f"y{yaw:03d}e{elev:+03d}", yaw, elev) for elev in (-30, 0, 25, 55) for yaw in range(0, 360, 30)]


def log(*a):
    print(*a, flush=True)


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
mesh = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not mesh]:
    bpy.data.objects.remove(o, do_unlink=True)
sc = bpy.context.scene

nt = mesh.data.materials[0].node_tree
bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
for l in list(bsdf.inputs["Metallic"].links):
    nt.links.remove(l)
bsdf.inputs["Metallic"].default_value = 0.0
fill_unwritten_texels(bsdf.inputs["Base Color"].links[0].from_node.image)

co = np.empty(len(mesh.data.vertices) * 3, np.float32)
mesh.data.vertices.foreach_get("co", co)
m = np.array(mesh.matrix_world)
P = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
zmin, zmax = float(P[:, 2].min()), float(P[:, 2].max())
h = zmax - zmin
cx, cy = float((P[:, 0].min() + P[:, 0].max()) / 2), float((P[:, 1].min() + P[:, 1].max()) / 2)

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
sc.render.resolution_x = sc.render.resolution_y = RES
sc.render.film_transparent = True
sc.view_settings.view_transform = "Standard"
sc.view_settings.look = "None"
for name, loc, energy in (("key", (-2, -3, 3), 2.5), ("fill", (3, -3, 1), 1.2), ("rim", (0, 3, 2), 1.5),
                          ("back", (1, 3, 1), 1.0)):
    L = bpy.data.lights.new(name, "SUN"); L.energy = energy
    o = bpy.data.objects.new(name, L); sc.collection.objects.link(o); o.location = loc
    o.rotation_euler = (Vector((0, 0, 0.5)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
w = bpy.data.worlds.new("w"); sc.world = w; w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.35, 0.35, 0.35, 1)

pos_mat = bpy.data.materials.new("posid"); pos_mat.use_nodes = True
pn = pos_mat.node_tree
for n in list(pn.nodes):
    pn.nodes.remove(n)
out = pn.nodes.new("ShaderNodeOutputMaterial"); em = pn.nodes.new("ShaderNodeEmission")
geo = pn.nodes.new("ShaderNodeNewGeometry")
enc = pn.nodes.new("ShaderNodeVectorMath"); enc.operation = "MULTIPLY_ADD"   # emission can't be negative
enc.inputs[1].default_value = (0.5, 0.5, 0.5); enc.inputs[2].default_value = (0.5, 0.5, 0.5)
pn.links.new(geo.outputs["Position"], enc.inputs[0]); pn.links.new(enc.outputs[0], em.inputs[0])
pn.links.new(em.outputs[0], out.inputs[0])

cams = []
for vname, yaw, elev in VIEWS:
    for cname, (zc, ortho) in CROPS.items():
        name = f"{vname}_{cname}"
        a, e = math.radians(yaw), math.radians(elev)
        d = Vector((math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)))
        centre = Vector((cx, cy, zmin + zc * h))
        cam.location = centre + d * 3.0
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        cam.data.ortho_scale = ortho * h
        # lit
        sc.render.engine = "BLENDER_EEVEE_NEXT"; sc.eevee.taa_render_samples = 32; sc.render.filter_size = 1.5
        sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_depth = "8"
        sc.render.image_settings.color_mode = "RGBA"
        sc.render.filepath = os.path.join(WORK, name + "_lit.png"); bpy.ops.render.render(write_still=True)
        # world position, no AA
        saved = [s.material for s in mesh.material_slots]
        for s in mesh.material_slots:
            s.material = pos_mat
        sc.eevee.taa_render_samples = 1; sc.render.filter_size = 0.0
        sc.render.image_settings.file_format = "OPEN_EXR"; sc.render.image_settings.color_depth = "32"
        sc.render.image_settings.exr_codec = "ZIP"    # lossless: same values, ~1/3 the disk
        sc.render.filepath = os.path.join(WORK, name + "_pos.exr"); bpy.ops.render.render(write_still=True)
        for s, mt in zip(mesh.material_slots, saved):
            s.material = mt
        cams.append({"name": name, "yaw": yaw, "elev": elev, "crop": cname})
        log("rendered", name)
json.dump({"glb": GLB, "res": RES, "height": h, "cams": cams}, open(os.path.join(WORK, "cams.json"), "w"), indent=1)
log("RENDER_OK")
