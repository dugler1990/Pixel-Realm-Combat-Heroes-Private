"""Find a source pose that makes a good idle *on the demon*, and save it as the canonical one.

    .venv-bpy/Scripts/python.exe idle_pick.py <rigged.glb> <roles.json> <bvh_dir> <out_dir>

Kimodo takes full-body pose keyframes via --constraints, so pinning frame 0 and the last frame
of every generation to one pose makes every clip start and end in idle by construction - no
baked blend, no prompt-wording gamble. But the pose has to look good on *him*, and it lives in
SOMA's skeleton, so it cannot be judged as a stick figure.

So: take candidate poses from the clips we already have (each clip's first frame, and its
quietest frame), pose the demon the way the retargeter would with that pose as its reference,
and render them all. Pick by eye, then pass the winner's index back as PICK=<n> to write
idle_pose.json - the reference for every clip's bind, and the basis for the Kimodo constraint.

The demon's pose at the reference is exactly "his bones aimed along the source's directions",
which is what retarget_bvh.py's bind_rot computes, so this previews the real thing.
"""
import glob
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from PIL import Image, ImageDraw

RIGGED, ROLES, BVH_DIR, OUT = (os.path.abspath(p) for p in sys.argv[1:5])
PICK = os.environ.get("PICK")
PX = 330
os.makedirs(OUT, exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.argv = sys.argv[:1]                       # retarget_bvh reads argv at import; keep it quiet
import importlib.util
spec = importlib.util.spec_from_file_location(
    "rb", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "retarget_bvh.py"))

R = json.load(open(ROLES))
# the same table retarget_bvh.py uses, inlined so this script does not need its argv
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
cam.data.ortho_scale = H * 1.3
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


def pose_demon(dirs):
    """Aim each of his bones along the given source directions - what bind_rot does."""
    for s, t in pairs:
        if s not in dirs:
            continue
        pb = tgt.pose.bones[t]
        dt = (rest_rot[t] @ Vector((0, 1, 0))).normalized()
        want = dt.rotation_difference((dirs[s] @ Vector((0, 1, 0))).normalized()).to_matrix()             @ rest_rot[t]
        loc = rest_head[t] if t == role_of(("root",)) else (tw @ pb.matrix).translation
        pb.matrix = tw.inverted() @ (Matrix.Translation(loc) @ want.to_4x4())
        bpy.context.view_layer.update()


def clear_pose():
    for pb in tgt.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    bpy.context.view_layer.update()


def shot(yaw):
    a = math.radians(yaw)
    cam.location = (4 * math.sin(a), -4 * math.cos(a), MID)
    cam.rotation_euler = (math.radians(90), 0, a)
    tmp = os.path.join(OUT, "_i.png")
    sc.render.filepath = tmp
    bpy.ops.render.render(write_still=True)
    return Image.open(tmp).convert("RGB")


# ---- gather candidates -------------------------------------------------------------------
Y = Vector((0, 1, 0))
cands = []
for path in sorted(glob.glob(os.path.join(BVH_DIR, "*.bvh"))):
    clip = os.path.splitext(os.path.basename(path))[0]
    before = set(bpy.data.objects)
    bpy.ops.import_anim.bvh(filepath=path, global_scale=0.01, rotate_mode="NATIVE")
    src = [o for o in bpy.data.objects if o not in before and o.type == "ARMATURE"][0]
    act = src.animation_data.action if src.animation_data else None
    f0, f1 = ((int(round(x)) for x in act.frame_range) if act else (1, 90))
    f0, f1 = int(f0), int(f1)

    names = [s for s, _ in pairs if s in src.pose.bones]
    per = []
    for fr in range(f0, f1 + 1):
        sc.frame_set(fr)
        bpy.context.view_layer.update()
        per.append({n: (src.matrix_world @ src.pose.bones[n].matrix).to_3x3().normalized()
                    for n in names})
    move = [sum(((per[i][n] @ Y) - (per[i - 1][n] @ Y)).length for n in names)
            for i in range(1, len(per))]
    lo = int(np.argmin(move[3:-3])) + 3 if len(move) > 8 else 0
    cands.append((clip + " f%d" % f0, per[0]))
    cands.append((clip + " quiet f%d" % (f0 + lo), per[lo]))
    bpy.data.objects.remove(src, do_unlink=True)
    if act:
        bpy.data.actions.remove(act)
    print("candidates from", clip, flush=True)

# ---- either render the contact sheet, or save the pick -------------------------------------
if PICK is None:
    cols = 6
    rows = (len(cands) + cols - 1) // cols
    sheet = Image.new("RGB", (PX * cols, PX * rows), (30, 30, 34))
    d = ImageDraw.Draw(sheet)
    for i, (label, dirs) in enumerate(cands):
        clear_pose()
        pose_demon(dirs)
        im = shot(25)
        sheet.paste(im, ((i % cols) * PX, (i // cols) * PX))
        tag = "%d  %s" % (i, label)
        d.text(((i % cols) * PX + 9, (i // cols) * PX + 9), tag, fill=(0, 0, 0))
        d.text(((i % cols) * PX + 8, (i // cols) * PX + 8), tag, fill=(255, 230, 80))
        print("rendered", i, label, flush=True)
    p = os.path.join(OUT, "IDLE_CANDIDATES.png")
    sheet.save(p)
    os.remove(os.path.join(OUT, "_i.png"))
    print("IDLE_SHEET", p, "- rerun with PICK=<n> to save that one", flush=True)
else:
    i = int(PICK)
    label, dirs = cands[i]
    out = os.path.join(OUT, "idle_pose.json")
    # Full orientation, not just the bone direction: the direction alone leaves the twist to be
    # taken from whatever frame each clip happens to start on, so clips would still not share an
    # exact start pose - which is the entire point of having a canonical one.
    json.dump({"from": label, "index": i,
               "rots": {k: [list(r) for r in m] for k, m in dirs.items()}},
              open(out, "w"), indent=1)
    clear_pose()
    pose_demon(dirs)
    im = Image.new("RGB", (PX * 2, PX))
    im.paste(shot(25), (0, 0))
    im.paste(shot(90), (PX, 0))
    im.save(os.path.join(OUT, "IDLE_POSE.png"))
    os.remove(os.path.join(OUT, "_i.png"))
    print("IDLE_POSE saved:", label, "->", out, flush=True)
