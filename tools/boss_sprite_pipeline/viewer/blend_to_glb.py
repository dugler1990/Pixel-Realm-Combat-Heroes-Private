"""Export every action in a baked .blend as its own glTF animation, for the browser viewer.

    .venv-bpy/Scripts/python.exe blend_to_glb.py <animated.blend> <out.glb>

retarget_bvh.py already writes an animated.glb, but with export_animation_mode="NLA_TRACKS" -
and the best-40 bake came out with **one** animation in it (W_single_jump_00) because only one
track was live at export time. The 40 actions are all in the .blend; "ACTIONS" mode exports one
glTF animation per action regardless of NLA state, which is what the viewer wants.

No rendering happens here. This is a file conversion.
"""
import os
import sys

import bpy

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
BLEND, OUT = (os.path.abspath(p) for p in ARGV[0:2])

bpy.ops.wm.open_mainfile(filepath=BLEND)

acts = sorted(a.name for a in bpy.data.actions)
print("actions in blend: %d" % len(acts), flush=True)
for a in acts:
    print("   ", a, flush=True)

arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
print("armatures %d  meshes %d" % (len(arms), len(meshes)), flush=True)

# The exporter walks the selection, so the rig and its skin both have to be in it. An unselected
# mesh exports as an armature with no skin, which loads as an invisible rig in three.js.
bpy.ops.object.select_all(action="DESELECT")
for o in arms + meshes:
    o.select_set(True)
if arms:
    bpy.context.view_layer.objects.active = arms[0]

os.makedirs(os.path.dirname(OUT), exist_ok=True)
bpy.ops.export_scene.gltf(
    filepath=OUT,
    export_format="GLB",
    use_selection=True,
    export_animations=True,
    export_animation_mode="ACTIONS",   # one glTF animation per action - the whole point
    export_nla_strips=False,
    export_bake_animation=True,
    export_optimize_animation_size=False,   # keep the keys; the clips are short
    export_apply=False,
)
print("WROTE %s  %.1f MB" % (OUT, os.path.getsize(OUT) / 1e6), flush=True)
