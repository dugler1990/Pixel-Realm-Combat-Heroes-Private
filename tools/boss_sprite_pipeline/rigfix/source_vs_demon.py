"""Render the SOURCE skeleton's motion beside the demon's, same clip, same angles.

    .venv-bpy/Scripts/python.exe source_vs_demon.py <animated.blend> <bvh_dir> <out_dir> [px] [step]

The point is diagnosis. When a clip looks wrong on the demon there are two possible causes and
they need completely different fixes:

  * the generated motion itself is bad  -> change the prompt, or the model
  * the motion is fine and the transfer broke it -> fix the retarget

Watching only the demon cannot tell them apart. So: left half is the source skeleton drawn as a
stick figure straight from its own joint positions, right half is the demon, at matching camera
angles and matching frames. Anything present on the left and missing on the right is ours.

Drawn rather than rendered because the source has no mesh - it is a bare armature.
"""
import glob
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw

BLEND, BVH_DIR, OUT = (os.path.abspath(p) for p in sys.argv[1:4])
PX = int(sys.argv[4]) if len(sys.argv) > 4 else 400
STEP = int(sys.argv[5]) if len(sys.argv) > 5 else 2
YAWS = (25, 90)
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.open_mainfile(filepath=BLEND)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
sc = bpy.context.scene

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
_v = mesh.data.vertices
zs = [(mesh.matrix_world @ _v[i].co).z for i in range(0, len(_v), 37)]
H, MID = max(zs) - min(zs), (max(zs) + min(zs)) * 0.5
cam.data.ortho_scale = H * 1.45
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

tmp = os.path.join(OUT, "_c.png")
ad = arm.animation_data


def demon_shot(yaw):
    a = math.radians(yaw)
    cam.location = (4 * math.sin(a), -4 * math.cos(a), MID)
    cam.rotation_euler = (math.radians(90), 0, a)
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    return Image.open(tmp).convert("RGB")


for bvh in sorted(glob.glob(os.path.join(BVH_DIR, "*.bvh"))):
    clip = os.path.splitext(os.path.basename(bvh))[0]
    if clip not in bpy.data.actions:
        print("skip", clip, "(no action)", flush=True)
        continue
    act = bpy.data.actions[clip]
    ad.action = act
    if hasattr(act, "slots") and hasattr(ad, "action_slot") and len(act.slots):
        ad.action_slot = act.slots[0]

    before = set(bpy.data.objects)
    bpy.ops.import_anim.bvh(filepath=bvh, global_scale=0.01, rotate_mode="NATIVE")
    src = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"][0]
    bones = [(pb.name, pb.parent.name if pb.parent else None) for pb in src.pose.bones]

    f0, f1 = int(act.frame_start), int(act.frame_end)
    d = os.path.join(OUT, clip)
    os.makedirs(d, exist_ok=True)
    for i, fr in enumerate(range(f0, f1 + 1, STEP)):
        sc.frame_set(fr)
        bpy.context.view_layer.update()
        P = {pb.name: (src.matrix_world @ pb.head, src.matrix_world @ pb.tail)
             for pb in src.pose.bones}
        allp = np.array([[v.x, v.y, v.z] for hw in P.values() for v in hw])
        row = []
        for yaw in YAWS:
            a = math.radians(yaw)
            c, sn = math.cos(a), math.sin(a)
            # source: orthographic projection matching the camera's yaw
            panel = Image.new("RGB", (PX, PX), (22, 22, 28))
            dr = ImageDraw.Draw(panel)
            hgt = allp[:, 2].max() - allp[:, 2].min()
            k = PX * 0.62 / max(hgt, 1e-6)
            cx = (allp[:, 0] * c + allp[:, 1] * sn).mean()
            cz = (allp[:, 2].max() + allp[:, 2].min()) * 0.5

            def put(v):
                x = (v.x * c + v.y * sn - cx) * k
                return (PX * 0.5 + x, PX * 0.5 - (v.z - cz) * k)

            for nm, (hh, tt) in P.items():
                lo = nm.lower()
                col = ((90, 200, 255) if lo.startswith("left") else
                       (255, 170, 80) if lo.startswith("right") else (230, 230, 230))
                dr.line([put(hh), put(tt)], fill=col, width=3)
            dr.text((9, 9), "SOURCE  %s" % ("front" if yaw == YAWS[0] else "side"), fill=(0, 0, 0))
            dr.text((8, 8), "SOURCE  %s" % ("front" if yaw == YAWS[0] else "side"),
                    fill=(120, 240, 255))
            row.append(panel)
            dm = demon_shot(yaw)
            dd = ImageDraw.Draw(dm)
            dd.text((9, 9), "DEMON", fill=(0, 0, 0))
            dd.text((8, 8), "DEMON", fill=(255, 230, 80))
            row.append(dm)
        sheet = Image.new("RGB", (PX * 4, PX))
        for j, im in enumerate(row):
            sheet.paste(im, (j * PX, 0))
        ds = ImageDraw.Draw(sheet)
        ds.text((9, PX - 26), "%s  f%d/%d" % (clip, fr, f1), fill=(0, 0, 0))
        ds.text((8, PX - 27), "%s  f%d/%d" % (clip, fr, f1), fill=(200, 200, 200))
        sheet.save(os.path.join(d, "%04d.png" % i))
    bpy.data.objects.remove(src, do_unlink=True)
    for a2 in list(bpy.data.actions):
        if a2.name.endswith("__src") or a2.name == clip + ".001":
            bpy.data.actions.remove(a2)
    print("compared", clip, len(range(f0, f1 + 1, STEP)), "frames", flush=True)

if os.path.exists(tmp):
    os.remove(tmp)
print("COMPARE_OK", OUT, flush=True)
