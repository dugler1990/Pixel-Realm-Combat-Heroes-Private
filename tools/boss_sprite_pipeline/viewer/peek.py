"""Render a few frames of one action to PNG, so the result can be checked without a browser.

    .venv-bpy/Scripts/python.exe peek.py <animated.blend> <action> <out_dir> [n] [px]

Why this exists: `dir_check.py` verifies only the direction each bone points. It is blind to
roll, to position, and to anything about how the mesh actually deforms - so a bake can read
0.0 deg on every bone and still come out visibly mangled. That happened on 2026-10-03: a
rebuilt script passed dir_check, was declared equivalent, and was not. The only check that
catches it is looking, and this makes looking cheap (a handful of frames, not a 900-frame
sequence at 16.6 s each).

Three evenly spaced frames by default, one camera, flat lighting, no sprite-pipeline settings -
this is a diagnostic, not a render.
"""
import math
import os
import sys

import bpy
from mathutils import Vector

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
BLEND, ACTION, OUT = os.path.abspath(ARGV[0]), ARGV[1], os.path.abspath(ARGV[2])
N = int(ARGV[3]) if len(ARGV) > 3 else 3
PX = int(ARGV[4]) if len(ARGV) > 4 else 480

bpy.ops.wm.open_mainfile(filepath=BLEND)
os.makedirs(OUT, exist_ok=True)

arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
act = bpy.data.actions.get(ACTION) or next(
    (a for a in bpy.data.actions if a.name.startswith(ACTION)), None)
if act is None:
    print("NO SUCH ACTION %r; have: %s" % (ACTION, [a.name for a in bpy.data.actions]), flush=True)
    raise SystemExit(1)

if arm.animation_data is None:
    arm.animation_data_create()
for t in arm.animation_data.nla_tracks:
    t.mute = True                       # the bake leaves clips parked in muted NLA tracks
arm.animation_data.action = act

sc = bpy.context.scene
engines = sc.render.bl_rna.properties["engine"].enum_items.keys()
sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
sc.eevee.taa_render_samples = 8
sc.render.resolution_x = sc.render.resolution_y = PX
sc.render.film_transparent = False

world = bpy.data.worlds.new("w")
sc.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.10, 0.10, 0.13, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
light = bpy.data.objects.new("key", bpy.data.lights.new("key", type="SUN"))
light.data.energy = 4.0
light.rotation_euler = (math.radians(58), 0, math.radians(35))
sc.collection.objects.link(light)

cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
cam = bpy.data.objects.new("cam", cam_data)
sc.collection.objects.link(cam)
sc.camera = cam

f0, f1 = (int(round(x)) for x in act.frame_range)
# frame the whole clip once so the figure cannot drift out of shot between samples
pts = []
for f in range(f0, f1 + 1, max((f1 - f0) // 8, 1)):
    sc.frame_set(f)
    bpy.context.view_layer.update()
    pts += [arm.matrix_world @ pb.head for pb in arm.pose.bones]
xs = [p.x for p in pts]; ys = [p.y for p in pts]; zs = [p.z for p in pts]
mid = Vector(((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2))
span = max(max(xs) - min(xs), max(zs) - min(zs), 1.0)
cam.data.ortho_scale = span * 1.5
a = math.radians(28)
cam.location = (mid.x + span * 3 * math.sin(a), mid.y - span * 3 * math.cos(a), mid.z)
cam.rotation_euler = (math.radians(90), 0, a)

step = max((f1 - f0) // max(N - 1, 1), 1)
for i in range(N):
    f = min(f0 + i * step, f1)
    sc.frame_set(f)
    bpy.context.view_layer.update()
    sc.render.filepath = os.path.join(OUT, "%s_f%04d.png" % (ACTION, f))
    bpy.ops.render.render(write_still=True)
    print("peek %s frame %d" % (ACTION, f), flush=True)
print("PEEK_DONE", OUT, flush=True)
