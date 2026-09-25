"""Render a frame with each candidate group hidden in turn, to name the dark mass.

    .venv-bpy/Scripts/python.exe hide_test.py <animated.blend> <action> <frame> <out.png>
"""
import json
import math
import os
import sys

import bpy
from mathutils import Vector
from PIL import Image, ImageDraw

BLEND, ACTION, FRAME, OUT = sys.argv[1], sys.argv[2], int(sys.argv[3]), os.path.abspath(sys.argv[4])
PX = 560
ROLE = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
R = json.load(open(ROLE))

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

WING = {R["wing_l"]["arm"], R["wing_l"]["fan"], R["wing_r"]["arm"], R["wing_r"]["fan"]}
ARM = set()
for s in ("arm_l", "arm_r"):
    ARM |= {R[s]["shoulder"], R[s]["elbow"], R[s]["wrist"], R[s]["hand"]} | set(R[s]["fingers"])
TAIL = set(R["tail"])
CASES = [("everything", None), ("no wings", WING), ("no arms", ARM), ("no tail", TAIL)]

gi = {g.index: g.name for g in mesh.vertex_groups}
keep = mesh.vertex_groups.new(name="_keep")
tmp = os.path.join(os.path.dirname(OUT), "_h.png")
tiles = []
for label, hide in CASES:
    for m in [m for m in mesh.modifiers if m.type == "MASK"]:
        mesh.modifiers.remove(m)
    if hide:
        idx = []
        for i, v in enumerate(mesh.data.vertices):
            gs = {gi.get(g.group): g.weight for g in v.groups if g.weight > 0.001}
            if gs and max(gs, key=gs.get) not in hide:
                idx.append(i)
        keep.remove(range(len(mesh.data.vertices)))
        keep.add(idx, 1.0, "REPLACE")
        m = mesh.modifiers.new("mask", "MASK")
        m.vertex_group = "_keep"
        # the mask must run after the armature, or it hides the rest-pose vertices
        while mesh.modifiers.find("mask") != len(mesh.modifiers) - 1:
            bpy.ops.object.modifier_move_down({"object": mesh}, modifier="mask")
    bpy.context.view_layer.update()
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    img = Image.open(tmp).convert("RGB")
    d = ImageDraw.Draw(img)
    d.text((9, 9), label, fill=(0, 0, 0))
    d.text((8, 8), label, fill=(255, 230, 80))
    tiles.append(img)
    print("rendered", label, flush=True)

sheet = Image.new("RGB", (PX * len(tiles), PX))
for i, t in enumerate(tiles):
    sheet.paste(t, (i * PX, 0))
sheet.save(OUT)
os.remove(tmp)
print("HIDE_TEST", OUT, flush=True)
