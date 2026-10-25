"""The idle pose on the demon and on the source skeleton, same angles, side by side.

    .venv-bpy/Scripts/python.exe idle_compare.py <rigged.glb> <roles.json> <idle_pose.json> <out.png>

The demon is rendered; the source is drawn as a stick figure over it in the same projection,
normalised to his height with its hips on his. If the two read as the same stance from every
angle then the pose that goes to Kimodo as a constraint is the pose he actually idles in.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from PIL import Image, ImageDraw

RIGGED, ROLES, IDLE, OUT = (os.path.abspath(p) for p in sys.argv[1:5])
PX = 420
YAWS = [0, 45, 90, 135, 180, 270]

R = json.load(open(ROLES))
IDLE_ROTS = {k: Matrix(v).to_3x3() for k, v in json.load(open(IDLE))["rots"].items()}
MAP = {
    "Hips": ("root",), "Spine1": ("spine",), "Chest": ("chest",), "Head": ("neck",),
    "LeftShoulder": ("arm_l", "shoulder"), "LeftArm": ("arm_l", "elbow"),
    "LeftForeArm": ("arm_l", "wrist"), "LeftHand": ("arm_l", "hand"),
    "RightShoulder": ("arm_r", "shoulder"), "RightArm": ("arm_r", "elbow"),
    "RightForeArm": ("arm_r", "wrist"), "RightHand": ("arm_r", "hand"),
    "LeftLeg": ("leg_l", "hip"), "LeftShin": ("leg_l", "knee"),
    "LeftFoot": ("leg_l", "ankle"), "LeftToeBase": ("leg_l", "foot"),
    "RightLeg": ("leg_r", "hip"), "RightShin": ("leg_r", "knee"),
    "RightFoot": ("leg_r", "ankle"), "RightToeBase": ("leg_r", "foot"),
}


def role_of(path):
    n = R
    for p in path:
        if p not in n:
            return None
        n = n[p]
    return n if isinstance(n, str) else None


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=RIGGED)
for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
    for o in list(coll.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(coll)
tgt = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
for pb in tgt.pose.bones:
    pb.rotation_mode = "QUATERNION"
sc = bpy.context.scene
tw = tgt.matrix_world

pairs = [(s, role_of(p)) for s, p in MAP.items()]
pairs = [(s, t) for s, t in pairs if t and t in tgt.pose.bones]


def bone_depth(b):
    d = 0
    while b.parent:
        b, d = b.parent, d + 1
    return d


pairs.sort(key=lambda st: bone_depth(tgt.data.bones[st[1]]))
rest_rot = {t: (tw @ tgt.data.bones[t].matrix_local).to_3x3().normalized() for _, t in pairs}
rest_head = {t: (tw @ tgt.data.bones[t].matrix_local).translation.copy() for _, t in pairs}
root = role_of(("root",))

Y = Vector((0, 1, 0))
for s, t in pairs:                                   # pose him exactly as the bind would
    if s not in IDLE_ROTS:
        continue
    pb = tgt.pose.bones[t]
    ds = (IDLE_ROTS[s].normalized() @ Y).normalized()
    dt = (rest_rot[t] @ Y).normalized()
    want = dt.rotation_difference(ds).to_matrix() @ rest_rot[t]
    loc = rest_head[t] if t == root else (tw @ pb.matrix).translation
    pb.matrix = tw.inverted() @ (Matrix.Translation(loc) @ want.to_4x4())
    bpy.context.view_layer.update()

# the source's own joint chain at that pose, walked from the hips using its bone lengths
SRC_LEN = {}
SRC_PARENT = {"Spine1": "Hips", "Chest": "Spine1", "Head": "Chest",
              "LeftShoulder": "Chest", "LeftArm": "LeftShoulder", "LeftForeArm": "LeftArm",
              "LeftHand": "LeftForeArm", "RightShoulder": "Chest", "RightArm": "RightShoulder",
              "RightForeArm": "RightArm", "RightHand": "RightForeArm",
              "LeftLeg": "Hips", "LeftShin": "LeftLeg", "LeftFoot": "LeftShin",
              "LeftToeBase": "LeftFoot", "RightLeg": "Hips", "RightShin": "RightLeg",
              "RightFoot": "RightShin", "RightToeBase": "RightFoot"}
for s, t in pairs:                                   # borrow his own bone lengths, scaled later
    SRC_LEN[s] = tgt.data.bones[t].length * tw.to_scale().x

head_pos = {"Hips": Vector((0, 0, 0))}
order = [s for s, _ in pairs]
for _ in range(4):
    for s in order:
        p = SRC_PARENT.get(s)
        if s in head_pos or p is None or p not in head_pos or p not in IDLE_ROTS:
            continue
        head_pos[s] = head_pos[p] + (IDLE_ROTS[p].normalized() @ Y).normalized() * SRC_LEN[p]
src_seg = {s: (head_pos[s], head_pos[s] + (IDLE_ROTS[s].normalized() @ Y).normalized() * SRC_LEN[s])
           for s in order if s in head_pos and s in IDLE_ROTS}

for sl in mesh.material_slots:
    nt = sl.material.node_tree
    b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    for l in list(b.inputs["Metallic"].links):
        nt.links.remove(l)
    b.inputs["Metallic"].default_value = 0
sc.render.engine = "BLENDER_EEVEE_NEXT"
sc.eevee.taa_render_samples = 12
sc.render.resolution_x = sc.render.resolution_y = PX
sc.view_settings.view_transform = "Standard"
sc.render.image_settings.file_format = "PNG"
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
dg = bpy.context.evaluated_depsgraph_get()
tm = mesh.evaluated_get(dg).to_mesh()
zz = [(mesh.matrix_world @ v.co).z for v in tm.vertices]
H, MID = max(zz) - min(zz), (max(zz) + min(zz)) * 0.5
mesh.evaluated_get(dg).to_mesh_clear()
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

hips_world = (tw @ tgt.pose.bones[root].matrix).translation
sheet = Image.new("RGB", (PX * 3, PX * 2), (30, 30, 34))
tmp = os.path.join(os.path.dirname(OUT), "_ic.png")
for i, yaw in enumerate(YAWS):
    a = math.radians(yaw)
    cam.location = (4 * math.sin(a), -4 * math.cos(a), MID)
    cam.rotation_euler = (math.radians(90), 0, a)
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    im = Image.open(tmp).convert("RGB")
    d = ImageDraw.Draw(im)
    c, sn = math.cos(a), math.sin(a)

    def put(v):
        p = v + hips_world
        # camera right vector for rotation_euler (90, 0, yaw) is (cos, sin, 0), not (cos, -sin, 0)
        x = (p.x - cam.location.x) * c + (p.y - cam.location.y) * sn
        return (PX * 0.5 + x / cam.data.ortho_scale * PX,
                PX * 0.5 - (p.z - MID) / cam.data.ortho_scale * PX)

    for s, (h, t2) in src_seg.items():
        col = (90, 240, 255) if "Left" in s else ((255, 190, 90) if "Right" in s else (255, 255, 255))
        d.line([put(h), put(t2)], fill=col, width=3)
        d.ellipse([put(h)[0] - 3, put(h)[1] - 3, put(h)[0] + 3, put(h)[1] + 3], fill=(20, 20, 20))
    lab = "yaw %d   lines = source skeleton at the same pose" % yaw
    d.text((9, 9), lab, fill=(0, 0, 0))
    d.text((8, 8), lab, fill=(255, 230, 80))
    sheet.paste(im, ((i % 3) * PX, (i // 3) * PX))
    print("angle", yaw, flush=True)
sheet.save(OUT)
os.remove(tmp)
print("IDLE_COMPARE", OUT, flush=True)
