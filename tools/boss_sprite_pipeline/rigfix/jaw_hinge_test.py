"""Current jaw hinge vs a lowered one, side by side, over a range of angles.

    .venv-bpy/Scripts/python.exe jaw_hinge_test.py <out.png> [new_z]

The jaw geometry spans z 0.118..0.193; the hinge sits at z 0.207, about 1.4 cm above the whole
jaw. Rotating about a point that floats above the jaw swings it back and up into the throat
rather than down and open, which is why no angle reads right - at -8 it has not closed and by
-14 it is scissoring into the neck. A real jaw hinges at the top-rear of the jaw itself.

Renders both hinges at each angle, left and right side views, so the difference is visible
where it actually shows. Nothing is written to the rig.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector
from PIL import Image, ImageDraw

GLB = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\rigged_jaw_smoothw.glb"
ROLE = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
OUT = os.path.abspath(sys.argv[1])
NEW_Z = float(sys.argv[2]) if len(sys.argv) > 2 else 0.193
ANGLES = [0, -8, -14, -20, -26]
PX = 300
YAWS = [(0, "front"), (90, "side")]

R = json.load(open(ROLE))
jaw = R["jaw"]


def build(lower):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=GLB)
    for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
        for o in list(coll.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(coll)
    arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
    mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
    if lower:
        bpy.context.view_layer.objects.active = arm
        bpy.ops.object.mode_set(mode="EDIT")
        eb = arm.data.edit_bones[jaw]
        eb.use_connect = False
        d = eb.tail - eb.head                       # keep length and direction, move the pivot
        eb.head = Vector((eb.head.x, eb.head.y, NEW_Z))
        eb.tail = eb.head + d
        bpy.ops.object.mode_set(mode="OBJECT")
    # the wing membrane sits right behind his head and hides the side profile entirely
    gi = {g.index: g.name for g in mesh.vertex_groups}
    wing = {R["wing_l"]["arm"], R["wing_l"]["fan"], R["wing_r"]["arm"], R["wing_r"]["fan"]}
    keep = mesh.vertex_groups.new(name="_nowing")
    idx = []
    for i, v in enumerate(mesh.data.vertices):
        gs = {gi.get(g.group): g.weight for g in v.groups if g.weight > 0.001}
        if gs and max(gs, key=gs.get) not in wing:
            idx.append(i)
    keep.add(idx, 1.0, "REPLACE")
    m = mesh.modifiers.new("mask", "MASK")
    m.vertex_group = "_nowing"
    for s in mesh.material_slots:
        nt = s.material.node_tree
        b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        for l in list(b.inputs["Metallic"].links):
            nt.links.remove(l)
        b.inputs["Metallic"].default_value = 0
    return arm, mesh


def setup_scene(arm):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE_NEXT"
    sc.eevee.taa_render_samples = 16
    sc.render.resolution_x = sc.render.resolution_y = PX
    sc.view_settings.view_transform = "Standard"
    sc.render.image_settings.file_format = "PNG"
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 0.26
    for n, loc, e in (("k", (-2, -3, 3), 5.0), ("f", (3, -3, 1), 3.0), ("b", (0, 3, 2), 1.5)):
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
    return sc, cam


tmp = os.path.join(os.path.dirname(OUT), "_jh.png")
cols = len(YAWS) * 2
sheet = Image.new("RGB", (PX * cols, PX * len(ANGLES)), (30, 30, 34))
d = ImageDraw.Draw(sheet)

for col_off, lower in ((0, False), (1, True)):
    arm, mesh = build(lower)
    sc, cam = setup_scene(arm)
    pb = arm.pose.bones[jaw]
    pb.rotation_mode = "QUATERNION"
    axis = ((arm.matrix_world @ arm.data.bones[jaw].matrix_local).to_3x3().inverted()
            @ Vector((1, 0, 0))).normalized()
    # FIXED camera target for both builds. Aiming at the jaw bone moves the camera when the
    # bone moves, which compares two framings rather than two jaws - the difference then reads
    # the same at 0 degrees, where the two builds are necessarily identical.
    aim = Vector((0.0, -0.128, 0.195))
    for r, deg in enumerate(ANGLES):
        pb.rotation_quaternion = Quaternion(axis, math.radians(deg))
        bpy.context.view_layer.update()
        for k, (yaw, tag) in enumerate(YAWS):
            a = math.radians(yaw)
            cam.location = (aim.x + 2 * math.sin(a), aim.y - 2 * math.cos(a), aim.z)
            cam.rotation_euler = (math.radians(90), 0, a)
            sc.render.filepath = tmp
            bpy.ops.render.render(write_still=True)
            x = (k * 2 + col_off) * PX
            sheet.paste(Image.open(tmp).convert("RGB"), (x, r * PX))
            lab = "%+d  %s  %s" % (deg, tag, "LOWERED" if lower else "current")
            d.text((x + 9, r * PX + 9), lab, fill=(0, 0, 0))
            d.text((x + 8, r * PX + 8), lab,
                   fill=(120, 255, 140) if lower else (255, 200, 80))
        print("row", deg, "lowered" if lower else "current", flush=True)

sheet.save(OUT)
os.remove(tmp)
print("JAW_HINGE", OUT, "(current hinge z 0.207, lowered to %.3f)" % NEW_Z, flush=True)
