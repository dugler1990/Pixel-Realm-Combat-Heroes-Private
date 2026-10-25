"""Render raw BVH as a shaded 3D mannequin - no demon, no retarget, no rig needed.

    blender -b -noaudio --python mannequin.py -- <cells_dir> <out_dir> [px] [step] [regex]

cell_reel.py draws the skeleton as flat 2D lines, which is enough to spot a dead clip but not
enough to judge a motion. Blender will not render an armature (bones are not renderable), so
this parents one box per bone: bone-parented boxes sit in bone space and follow the animation
for free, no per-frame keyframing and no skinning.

One sample per cell (the first), two camera angles per frame, the cell name burned in.
"""
import glob
import math
import os
import re
import sys

import bpy
from mathutils import Vector

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
SRC, OUT = (os.path.abspath(p) for p in ARGV[0:2])
PX = int(ARGV[2]) if len(ARGV) > 2 else 480
STEP = int(ARGV[3]) if len(ARGV) > 3 else 6
PAT = re.compile(ARGV[4]) if len(ARGV) > 4 else None
os.makedirs(OUT, exist_ok=True)


def build(bvh_path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_anim.bvh(filepath=bvh_path, global_scale=0.01, rotate_mode="NATIVE")
    arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]

    mat = bpy.data.materials.new("skin")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.62, 0.66, 0.74, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.55

    for bone in arm.data.bones:
        ln = bone.length
        if ln < 1e-4:
            continue
        # width scales with bone length so fingers do not come out as fence posts
        w = max(min(ln * 0.30, 0.055), 0.012)
        bpy.ops.mesh.primitive_cube_add(size=1.0)
        box = bpy.context.active_object
        box.scale = (w, ln * 0.5, w)
        box.data.materials.append(mat)
        # Bone parenting puts the child's origin at the bone TAIL, so step back half a bone
        box.parent = arm
        box.parent_type = "BONE"
        box.parent_bone = bone.name
        box.matrix_parent_inverse.identity()
        box.location = (0.0, -ln * 0.5, 0.0)
        box.rotation_euler = (0.0, 0.0, 0.0)
    return arm


def setup_scene():
    sc = bpy.context.scene
    # 4.x calls it BLENDER_EEVEE_NEXT, 5.x renamed it back to BLENDER_EEVEE
    engines = sc.render.bl_rna.properties["engine"].enum_items.keys()
    sc.render.engine = ("BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines
                        else "BLENDER_EEVEE")
    sc.eevee.taa_render_samples = 8
    sc.render.resolution_x = sc.render.resolution_y = PX
    sc.render.film_transparent = False
    world = bpy.data.worlds.new("w")
    sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.09, 0.09, 0.12, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.45

    light_data = bpy.data.lights.new("key", type="SUN")
    light_data.energy = 3.0
    light = bpy.data.objects.new("key", light_data)
    sc.collection.objects.link(light)
    light.rotation_euler = (math.radians(55), 0, math.radians(35))

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"          # ortho so the figure keeps one size all clip
    cam = bpy.data.objects.new("cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    return sc, cam


cells = sorted(d for d in glob.glob(os.path.join(SRC, "*")) if os.path.isdir(d))
idx = 0
for d in cells:
    name = os.path.basename(d)
    if PAT and not PAT.search(name):
        continue
    fs = sorted(glob.glob(os.path.join(d, "*.bvh")))
    if not fs:
        continue
    arm = build(fs[0])
    sc, cam = setup_scene()
    act = arm.animation_data.action
    f0, f1 = (int(round(x)) for x in act.frame_range)

    # frame the whole clip once, so the figure does not swim around between frames
    pts = []
    for f in range(f0, f1 + 1, max((f1 - f0) // 12, 1)):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        pts += [arm.matrix_world @ pb.head for pb in arm.pose.bones]
    xs = [p.x for p in pts]; ys = [p.y for p in pts]; zs = [p.z for p in pts]
    mid = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2))
    span = max(max(xs) - min(xs), max(zs) - min(zs), 1.2)
    dist = span * 2.4
    cam.data.ortho_scale = span * 1.15   # fills the frame; no perspective swim

    dd = os.path.join(OUT, "%03d_%s" % (idx, name))
    os.makedirs(dd, exist_ok=True)
    for i, f in enumerate(range(f0, f1 + 1, STEP)):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        for k, yaw in enumerate((25.0, 90.0)):
            a = math.radians(yaw)
            cam.location = (mid.x + dist * math.sin(a), mid.y - dist * math.cos(a), mid.z)
            cam.rotation_euler = (math.radians(90), 0, a)
            sc.render.filepath = os.path.join(dd, "%04d_%d.png" % (i, k))
            bpy.ops.render.render(write_still=True)
    print("mannequin %03d %-34s %d frames" % (idx, name[:34], len(range(f0, f1 + 1, STEP))),
          flush=True)
    idx += 1
print("MANNEQUIN_DONE", idx, OUT, flush=True)
