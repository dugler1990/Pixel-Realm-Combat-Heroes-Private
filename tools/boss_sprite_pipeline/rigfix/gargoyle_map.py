"""Retarget the free winged-gargoyle rig's actions onto the demon, wings included.

    .venv-bpy/Scripts/python.exe gargoyle_map.py <source.glb> <rigged.glb> <roles.json> <out_dir>

Kimodo's skeleton has no wings, no tail and no jaw, so those bones sit dead in every clip we
have. This source does have them - 57 bones, 42 actions, 16 wing bones that all animate - and
it is a winged biped rather than a human, so the proportion mismatch is far smaller too.

Same transfer as retarget_bvh.py (world-space rotation delta against a reference pose); only
the bone table changes. The source uses 3ds Max Biped naming.
"""
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

SRC_GLB, RIGGED, ROLES, OUT = (os.path.abspath(p) for p in sys.argv[1:5])
os.makedirs(OUT, exist_ok=True)
LIMIT = int(os.environ.get("CLIP_LIMIT", "6"))

R = json.load(open(ROLES))


def role(path):
    n = R
    for p in path:
        if p not in n:
            return None
        n = n[p]
    return n if isinstance(n, str) else None


# Source (3ds Max Biped + wings) -> ours. Role names are off by one on the arms, see
# bone_roles.json `_anatomy`: "elbow" is the upper arm, "wrist" the forearm.
MAP = {
    "Bip01-Pelvis": role(("root",)),
    "Bip01-Spine": role(("spine",)),
    "Bip01-Spine2": role(("chest",)),
    "Bip01-Head": role(("neck",)),                       # bone_13 is the actual head
    "Bone_Jaw": R.get("jaw"),
    "Bip01-L-Clavicle": role(("arm_l", "shoulder")),
    "Bip01-L-UpperArm": role(("arm_l", "elbow")),
    "Bip01-L-Forearm": role(("arm_l", "wrist")),
    "Bip01-L-Hand": role(("arm_l", "hand")),
    "Bip01-R-Clavicle": role(("arm_r", "shoulder")),
    "Bip01-R-UpperArm": role(("arm_r", "elbow")),
    "Bip01-R-Forearm": role(("arm_r", "wrist")),
    "Bip01-R-Hand": role(("arm_r", "hand")),
    "Bip01-L-Thigh": role(("leg_l", "hip")),
    "Bip01-L-Calf": role(("leg_l", "knee")),
    "Bip01-L-Foot": role(("leg_l", "ankle")),
    "Bip01-R-Thigh": role(("leg_r", "hip")),
    "Bip01-R-Calf": role(("leg_r", "knee")),
    "Bip01-R-Foot": role(("leg_r", "ankle")),
    # the whole point: wings
    "Bone_Lwing001": R["wing_l"]["arm"],
    "Bone_Lwing002": R["wing_l"]["fan"],
    "Bone_Rwing001": R["wing_r"]["arm"],
    "Bone_Rwing002": R["wing_r"]["fan"],
}


def log(*a):
    print("[gargoyle]", *a, flush=True)


def depth(b):
    d = 0
    while b.parent:
        b, d = b.parent, d + 1
    return d


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
tw = tgt.matrix_world

before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=SRC_GLB)
src = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"][0]
src_names = {b.name for b in src.data.bones}

# the source prefixes vary between exports; match by suffix so the table survives that
pairs = []
for s, t in MAP.items():
    if not t or t not in tgt.pose.bones:
        continue
    hit = next((n for n in src_names if n == s or n.startswith(s + "_") or
                n.split(":")[-1].split("_")[0] == s), None)
    if hit:
        pairs.append((hit, t))
pairs.sort(key=lambda st: depth(tgt.data.bones[st[1]]))
log("matched %d of %d bones" % (len(pairs), len(MAP)))
log("unmatched:", [s for s in MAP if not any(p[0] == s or p[0].startswith(s) for p in pairs)])
wings = [t for s, t in pairs if "wing" in t.lower()]
log("wing bones driven:", wings)

rest_rot = {t: (tw @ tgt.data.bones[t].matrix_local).to_3x3().normalized() for _, t in pairs}
rest_head = {t: (tw @ tgt.data.bones[t].matrix_local).translation.copy() for _, t in pairs}
root_name = role(("root",))
sc = bpy.context.scene
acts = sorted(bpy.data.actions, key=lambda a: a.name)[:LIMIT]
log("clips:", [a.name.split("|")[-1][:28] for a in acts])

src_ad = src.animation_data
out_actions = {}
for act in acts:
    src_ad.action = act
    if hasattr(act, "slots") and hasattr(src_ad, "action_slot") and len(act.slots):
        src_ad.action_slot = act.slots[0]
    f0, f1 = (int(round(x)) for x in act.frame_range)
    f0, f1 = max(f0, 0), int(f1)

    def sw(n):
        return src.matrix_world @ src.pose.bones[n].matrix

    sc.frame_set(f0)
    bpy.context.view_layer.update()
    ref_inv = {s: sw(s).to_3x3().normalized().inverted() for s, _ in pairs}
    ref_root = sw(pairs[0][0]).translation.copy()
    for s, t in pairs:
        if t == root_name:
            ref_root = sw(s).translation.copy()
    src_h = max((src.matrix_world @ pb.head).z for pb in src.pose.bones)
    tgt_h = max((tw @ pb.head).z for pb in tgt.pose.bones)
    travel = tgt_h / max(src_h, 1e-6)

    tgt.animation_data_clear()
    for fr in range(f0, f1 + 1):
        sc.frame_set(fr)
        bpy.context.view_layer.update()
        for s, t in pairs:
            pb = tgt.pose.bones[t]
            m = sw(s)
            want = (m.to_3x3().normalized() @ ref_inv[s]) @ rest_rot[t]
            loc = (rest_head[t] + (m.translation - ref_root) * travel
                   if t == root_name else (tw @ pb.matrix).translation)
            pb.matrix = tw.inverted() @ (Matrix.Translation(loc) @ want.to_4x4())
            bpy.context.view_layer.update()
            pb.keyframe_insert("rotation_quaternion", frame=fr)
            if t == root_name:
                pb.keyframe_insert("location", frame=fr)
    a = tgt.animation_data.action
    a.name = "gar_" + act.name.split("|")[-1][:24]
    a.use_fake_user = True
    a.use_frame_range = True
    a.frame_start, a.frame_end = f0, f1
    ad = tgt.animation_data
    ad.action = None
    tr = ad.nla_tracks.new()
    tr.name = a.name
    tr.strips.new(a.name, f0, a)
    tr.mute = True
    out_actions[a.name] = a
    log("retargeted", a.name, f1 - f0 + 1, "frames")

bpy.data.objects.remove(src, do_unlink=True)
for img in bpy.data.images:
    if img.users and not img.packed_file:
        try:
            img.pack()
        except RuntimeError:
            pass
blend = os.path.join(OUT, "animated.blend")
bpy.ops.wm.save_as_mainfile(filepath=blend)
log("saved", blend, "with", len(out_actions), "actions")
