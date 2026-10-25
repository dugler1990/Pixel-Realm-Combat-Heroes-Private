"""Colour every vertex by which bone group owns it, and render rest + the bad frame.

    .venv-bpy/Scripts/python.exe owner_map.py <animated.blend> <action> <frame> <out.png>

red = arm bones, green = wing bones, blue = torso/chest, yellow = tail, magenta = head,
grey = everything else. Whatever the dark shredded mass is, it will name itself.
"""
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from PIL import Image, ImageDraw

BLEND, ACTION, FRAME, OUT = sys.argv[1], sys.argv[2], int(sys.argv[3]), os.path.abspath(sys.argv[4])
PX = 620
ROLE = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
import json
R = json.load(open(ROLE))

bpy.ops.wm.open_mainfile(filepath=os.path.abspath(BLEND))
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
sc = bpy.context.scene

ARM = set()
for s in ("arm_l", "arm_r"):
    ARM |= {R[s]["shoulder"], R[s]["elbow"], R[s]["wrist"], R[s]["hand"]} | set(R[s]["fingers"])
WING = {R["wing_l"]["arm"], R["wing_l"]["fan"], R["wing_r"]["arm"], R["wing_r"]["fan"]}
TORSO = {R["root"], R["spine"], R["chest"]}
TAIL = set(R["tail"])
HEAD = {R["neck"], R["head"], R.get("jaw")}
COL = [(ARM, (1.0, 0.12, 0.12)), (WING, (0.15, 1.0, 0.2)), (TORSO, (0.2, 0.35, 1.0)),
       (TAIL, (1.0, 0.9, 0.1)), (HEAD, (1.0, 0.2, 1.0))]

gi = {g.index: g.name for g in mesh.vertex_groups}
nv = len(mesh.data.vertices)
cols = np.tile(np.array([0.45, 0.45, 0.45, 1.0]), (nv, 1))
tally = {}
for i, v in enumerate(mesh.data.vertices):
    gs = {gi.get(g.group): g.weight for g in v.groups if g.weight > 0.001}
    if not gs:
        continue
    d = max(gs, key=gs.get)
    for names, c in COL:
        if d in names:
            cols[i, :3] = c
            break
    tally[d] = tally.get(d, 0) + 1

attr = mesh.data.color_attributes.new(name="owner", type="FLOAT_COLOR", domain="POINT")
attr.data.foreach_set("color", cols.ravel())
mat = bpy.data.materials.new("ownermat")
mat.use_nodes = True
nt = mat.node_tree
for n in list(nt.nodes):
    nt.nodes.remove(n)
a = nt.nodes.new("ShaderNodeAttribute")
a.attribute_name = "owner"
e = nt.nodes.new("ShaderNodeEmission")
o = nt.nodes.new("ShaderNodeOutputMaterial")
nt.links.new(a.outputs["Color"], e.inputs["Color"])
nt.links.new(e.outputs["Emission"], o.inputs["Surface"])
mesh.data.materials.clear()
mesh.data.materials.append(mat)

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
ZOOM = float(os.environ.get("ZOOM", "1.35"))
ZUP = float(os.environ.get("ZUP", "0.0"))
cam.data.ortho_scale = H * ZOOM
w = bpy.data.worlds.new("w")
sc.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.05, 0.05, 0.06, 1)

ad = arm.animation_data
tmp = os.path.join(os.path.dirname(OUT), "_o.png")


def shot(yaw):
    ang = math.radians(yaw)
    cam.location = (4 * math.sin(ang), -4 * math.cos(ang), MID + ZUP * H)
    cam.rotation_euler = (math.radians(90), 0, ang)
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    return Image.open(tmp).convert("RGB")


tiles = []
for tag, act_name, fr in (("REST", None, None), (ACTION, ACTION, FRAME)):
    if act_name:
        act = bpy.data.actions[act_name]
        ad.action = act
        if hasattr(act, "slots") and hasattr(ad, "action_slot") and len(act.slots):
            ad.action_slot = act.slots[0]
        sc.frame_set(fr)
    else:
        ad.action = None
    bpy.context.view_layer.update()
    for yaw in (25, 110):
        im = shot(yaw)
        d = ImageDraw.Draw(im)
        t = "%s yaw %d" % (tag, yaw)
        d.text((9, 9), t, fill=(0, 0, 0))
        d.text((8, 8), t, fill=(255, 255, 255))
        tiles.append(im)
        print("shot", tag, yaw, flush=True)

sheet = Image.new("RGB", (PX * 2, PX * 2))
for i, t in enumerate(tiles):
    sheet.paste(t, ((i % 2) * PX, (i // 2) * PX))
sheet.save(OUT)
os.remove(tmp)
print("top owners:", sorted(tally.items(), key=lambda kv: -kv[1])[:8], flush=True)
print("OWNER_MAP", OUT, flush=True)
