"""Export a baked .blend as one mesh glb plus one tiny glb per clip.

    .venv-bpy/Scripts/python.exe export_split.py <animated.blend> <out_dir> [base_name]

Why split: exporting mesh+animations together re-extracts the 120k-triangle demon and rewrites
55 MB for every batch, which is ~10 s of fixed cost plus a full mesh write each time. The viewer
only needs the mesh once. So:

    <out>/base.glb          mesh + armature, NO animations   (~55 MB, written once)
    <out>/clips/<name>.glb  armature + ONE action, no mesh    (a few hundred KB each)

The clip files deliberately still go through Blender's glTF exporter rather than dumping fcurves
to JSON by hand: the exporter is what converts Blender's Z-up, bone-local, W-first quaternions
into glTF's Y-up node transforms, and reimplementing that conversion is exactly the kind of thing
that produces a demon lying on his side. Node names are identical in both files, so three.js can
play a clip's AnimationClip against the skeleton loaded from base.glb.

Run with --clips-only once base.glb exists, which is the normal case after the first time.
"""
import os
import sys

import bpy

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
BLEND = os.path.abspath(ARGV[0])
OUT = os.path.abspath(ARGV[1])
CLIPS_ONLY = "--clips-only" in ARGV

bpy.ops.wm.open_mainfile(filepath=BLEND)
os.makedirs(os.path.join(OUT, "clips"), exist_ok=True)

arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not arms:
    print("NO ARMATURE in", BLEND, flush=True)
    raise SystemExit(1)
arm = arms[0]
acts = sorted(bpy.data.actions, key=lambda a: a.name)
print("armature %s  meshes %d  actions %d" % (arm.name, len(meshes), len(acts)), flush=True)


def select(objs):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]


base = os.path.join(OUT, "base.glb")
if not CLIPS_ONLY or not os.path.exists(base):
    # The mesh must be in the selection or the skin is dropped and the rig loads invisible.
    select([arm] + meshes)
    bpy.ops.export_scene.gltf(filepath=base, export_format="GLB", use_selection=True,
                              export_animations=False, export_apply=False)
    print("BASE %s  %.1f MB" % (base, os.path.getsize(base) / 1e6), flush=True)
else:
    print("BASE exists, skipped", flush=True)

# Armature only from here. Dropping the mesh from the *selection* stops it being written, but
# that alone is not the win: the exporter samples the depsgraph once per frame, and an unselected
# mesh is still evaluated - 662k vertices of armature deform per frame, which is what made a
# single clip take ~8 minutes. Hiding it from the viewport takes it out of evaluation entirely.
# Same measured 10x as the retarget bake. (base.glb is already written, so nothing below needs
# the mesh visible.)
for m in meshes:
    m.hide_viewport = True

if arm.animation_data is None:
    arm.animation_data_create()
for a in acts:
    arm.animation_data.action = a
    f0, f1 = (int(round(x)) for x in a.frame_range)
    bpy.context.scene.frame_start, bpy.context.scene.frame_end = f0, f1
    select([arm])
    p = os.path.join(OUT, "clips", "%s.glb" % a.name)
    bpy.ops.export_scene.gltf(filepath=p, export_format="GLB", use_selection=True,
                              export_animations=True, export_animation_mode="ACTIONS",
                              export_nla_strips=False, export_bake_animation=True,
                              export_optimize_animation_size=False, export_apply=False)
    print("CLIP %-34s %5d frames  %6.1f KB"
          % (a.name, f1 - f0 + 1, os.path.getsize(p) / 1e3), flush=True)

print("SPLIT_DONE %d clips -> %s" % (len(acts), OUT), flush=True)
