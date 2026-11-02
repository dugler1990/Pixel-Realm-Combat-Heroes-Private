"""Render a rigged GLB in its own paint, at rest and in the cut pose (check sheet).

    .venv-bpy/Scripts/python.exe pose_render.py <rigged.glb> <roles.json> <out.png>

CUT_POSE (shared with step 2): upper arms raised 70 deg (A-pose -> just above horizontal, armpits open),
legs spread 20 deg each (inner thighs open). Workbench, texture colour, no specular (Workbench's gloss
is not in the paint). Views: front, 3/4, side, back, and from below.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "explode"))
from explode_common import world_verts

RES = 640


def cut_pose(roles):
    al, ar, ll, lr = roles["arm_l"], roles["arm_r"], roles["leg_l"], roles["leg_r"]
    return [(al["elbow"], "Y", -70), (ar["elbow"], "Y", 70), (ll["hip"], "Y", -20), (lr["hip"], "Y", 20)]


def apply_pose(arm, rots):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    M = arm.matrix_world
    for bone, axis, deg in rots:
        pb = arm.pose.bones[bone]
        h = M @ pb.head
        R = Matrix.Translation(h) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-h)
        pb.matrix = M.inverted() @ R @ M @ pb.matrix
        bpy.context.view_layer.update()


if __name__ == "__main__":
    GLB, ROLES, OUT = (os.path.abspath(a) for a in sys.argv[1:4])
    roles = json.load(open(ROLES))
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=GLB)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    P = world_verts(mesh)
    h = float(np.ptp(P[:, 2]))
    centre = Vector(((P.min(0) + P.max(0)) / 2).tolist())
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "TEXTURE"
    sc.display.shading.show_specular_highlight = False
    sc.render.resolution_x = sc.render.resolution_y = RES
    sc.world = bpy.data.worlds.new("w")
    sc.world.color = (0.3, 0.3, 0.32)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = h * 1.3
    VIEWS = {"front": (0, -1, 0), "3/4": (-0.7, -0.7, 0), "side": (1, 0, 0), "back": (0, 1, 0),
             "below": (0, -0.35, -0.94)}
    POSES = {"rest": [], "cut pose": cut_pose(roles)}
    tmp = OUT[:-4] + "_frames"
    os.makedirs(tmp, exist_ok=True)
    LABEL = 22
    sheet = Image.new("RGB", (RES * len(VIEWS), (RES + LABEL) * len(POSES)), (25, 25, 28))
    draw = ImageDraw.Draw(sheet)
    for r, (pname, rots) in enumerate(POSES.items()):
        apply_pose(arm, rots)
        y = r * (RES + LABEL)
        draw.text((6, y + 4), f"{pname} | {os.path.basename(GLB)}      " + "   ".join(VIEWS), fill=(230, 230, 230))
        for c, (vname, d) in enumerate(VIEWS.items()):
            d = Vector(d).normalized()
            cam.location = centre + d * h * 3
            cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
            sc.render.filepath = os.path.join(tmp, f"{pname}_{vname}.png".replace(" ", "_").replace("/", ""))
            bpy.ops.render.render(write_still=True)
            sheet.paste(Image.open(sc.render.filepath).convert("RGB"), (c * RES, y + LABEL))
    sheet.save(OUT)
    print("POSE_RENDER_OK", OUT, flush=True)
