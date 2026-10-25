"""Take the torso back off the arm bones.

owner_map.py settles what every earlier theory got wrong. Coloured by owning bone, the REST
pose shows the arm chain (bone_14/15/16/17 and 24/25/26/27) owning the whole upper chest and
both pectorals, right across the midline; the chest bone only gets the abdomen. Raise the arms
and that slab of torso goes up with them, leaving the chest exposed underneath - the dark
shredded mass in push1, groundsmash1 and taunt1, and the "chest/neck area opening weirdly".

Re-parenting the clavicles did not touch this, because the fault is weight, not hierarchy.

Fix: for anything the arm chain owns, fade its arm weight out towards the midline and hand it
to the chest. INNER = pure chest, OUTER = leave alone, smoothstep between, so the deltoid and
the arm proper keep their weight and only the slab over the ribcage moves. The arms sit at
|x| 0.12-0.23 at rest, well outside OUTER, so they are untouched by construction.

Writes rigged_jaw_chestfix.glb.
"""
import json
import os

import bpy

RIG = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\rigged_jaw_headfix.glb"
ROLES = r"C:\Users\Douglas\Pixel-Realm-Combat-Heroes-Boss\generated\bosses\demon\rig\jaw\bone_roles.json"
OUT = os.path.dirname(RIG)
INNER, OUTER = 0.055, 0.100        # the clavicle head is at |x| 0.067, the upper arm at 0.123

R = json.load(open(ROLES))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=RIG)
for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
    for o in list(coll.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(coll)
arm_o = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
chest = R["chest"]

ARM = set()
for s in ("arm_l", "arm_r"):
    ARM |= {R[s]["shoulder"], R[s]["elbow"], R[s]["wrist"], R[s]["hand"]} | set(R[s]["fingers"])

vg = {g.name: g for g in mesh.vertex_groups}
if chest not in vg:
    vg[chest] = mesh.vertex_groups.new(name=chest)
gi = {g.index: g.name for g in mesh.vertex_groups}
mw = mesh.matrix_world

moved = 0.0
n = 0
for v in mesh.data.vertices:
    hit = {gi.get(g.group): g.weight for g in v.groups
           if gi.get(g.group) in ARM and g.weight > 0.0}
    if not hit:
        continue
    x = abs((mw @ v.co).x)
    if x >= OUTER:
        continue
    t = 0.0 if x <= INNER else (x - INNER) / (OUTER - INNER)
    keep = t * t * (3 - 2 * t)                       # 0 at the midline, 1 out at the deltoid
    give = sum(w for w in hit.values()) * (1.0 - keep)
    if give <= 1e-5:
        continue
    for name, w in hit.items():
        vg[name].add([v.index], w * keep, "REPLACE")
    cw = next((g.weight for g in v.groups if gi.get(g.group) == chest), 0.0)
    vg[chest].add([v.index], cw + give, "REPLACE")
    moved += give
    n += 1
print("moved %.0f weight units off the arms onto the chest, over %d vertices" % (moved, n),
      flush=True)

for img in bpy.data.images:
    if img.users and not img.packed_file:
        try:
            img.pack()
        except RuntimeError:
            pass
bpy.ops.object.select_all(action="DESELECT")
mesh.select_set(True)
arm_o.select_set(True)
bpy.context.view_layer.objects.active = arm_o
out = os.path.join(OUT, "rigged_jaw_chestfix.glb")
bpy.ops.export_scene.gltf(filepath=out, use_selection=True)
print("EXPORTED", out, flush=True)
