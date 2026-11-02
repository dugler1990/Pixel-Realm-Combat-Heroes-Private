"""Step 8: pose test — the exploded parts worn over the naked rigged body.

    .venv-bpy/Scripts/python.exe explode_pose.py [--hide-body] [--texture] <base_rigged.glb> <roles.json> <out_dir> <label>=<parts.glb> [...]

For each parts GLB (one object per part, all in the outfit's frame: input_parts.glb = cut shells,
merged_parts.glb = shells + HoloPart infill):
1. align   one similarity for all parts, as whole_fit.py: scale from height, then the parts' head
           ICP-matched onto the base head
2. weights each part vertex copies the base skin weights of its 4 nearest body vertices
           (inverse distance, top 4 bones)
3. render  the body stays visible in bright green under the parts: any green showing in a pose is
           a gap between parts or body poking through. Parts in flat part colours.
           --hide-body: the body is not rendered and backfaces are culled, on a red background:
           red inside the figure = a see-through gap (a game hides the body under worn gear).
           --texture: parts in their own paint instead of flat part colours.
           No parts GLB given (use with --texture): the bare rigged body alone, in the same poses.
           --dqs: Blender "Preserve Volume" (dual quaternion) skinning on every mesh. Sprite route only:
           the in-game GPU skinning (PLAN_mesh_skinning.md) is linear blend.
           --rigid: armour weights by piece instead of copied skin (rigid_weights below): plates move
           as plates; the pauldron rides half collarbone / half upper arm; the skirt blends to the thighs.
Writes POSE_<label>.png (poses x views) per variant and POSE_COMPARE.png (key poses side by side).
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector, kdtree
from PIL import Image, ImageDraw

from explode_common import world_verts

HIDE_BODY = "--hide-body" in sys.argv
TEXTURE = "--texture" in sys.argv
DQS = "--dqs" in sys.argv
RIGID = "--rigid" in sys.argv
ARGS = [a for a in sys.argv[1:] if a not in ("--hide-body", "--texture", "--dqs", "--rigid")]
BASE, ROLES, OUT = (os.path.abspath(a) for a in ARGS[:3])
VARIANTS = [(a.split("=", 1)[0], os.path.abspath(a.split("=", 1)[1])) for a in ARGS[3:]]
os.makedirs(OUT, exist_ok=True)
RES = 512
HEAD_FRAC = 0.12
PALETTE = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
           (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (220, 190, 255),
           (170, 110, 40), (255, 250, 200)]
BODY_COLOUR = (0.05, 1.0, 0.1, 1)


def log(*a):
    print(*a, flush=True)


def kd(points):
    t = kdtree.KDTree(len(points))
    for i, p in enumerate(points):
        t.insert(p, i)
    t.balance()
    return t


def nearest(tree, points, k=1):
    idx = np.empty((len(points), k), np.int64)
    dist = np.empty((len(points), k), np.float32)
    for i, p in enumerate(points):
        for j, (_, n, d) in enumerate(tree.find_n(p, k)):
            idx[i, j], dist[i, j] = n, d
    return idx, dist


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=BASE)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not body]:
    bpy.data.objects.remove(o, do_unlink=True)
body.color = BODY_COLOUR
roles = json.load(open(ROLES))
B = world_verts(body)
hB = float(np.ptp(B[:, 2]))
tree_body = kd(B)
gnames = [g.name for g in body.vertex_groups]
W = np.zeros((len(B), len(gnames)), np.float32)
for v in body.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
head_b = B[B[:, 2] > B[:, 2].max() - HEAD_FRAC * hB]
tree_head = kd(head_b)


def box_anchor(P):
    return np.array([(P[:, 0].min() + P[:, 0].max()) / 2, (P[:, 1].min() + P[:, 1].max()) / 2, P[:, 2].min()])


def rigid_weights(part, P, Wa):
    """Plate armour: each piece moves with fixed bones, not with the skin under it."""
    base, side = (part[:-2], part[-1]) if part[-2:] in ("_l", "_r") else (part, None)
    arm_r, leg_r = (roles.get(f"arm_{side}"), roles.get(f"leg_{side}")) if side else (None, None)
    gi = gnames.index
    out = np.zeros_like(Wa)
    if base in ("head", "torso", "belt"):                       # one bone, 100 %
        out[:, gi(roles[{"head": "head", "torso": "chest", "belt": "root"}[base]])] = 1
    elif base == "pauldron":                                     # the helper-bone trick: halfway
        out[:, gi(arm_r["shoulder"])] = 0.5
        out[:, gi(arm_r["elbow"])] = 0.5
    elif base == "skirt":                                        # hips at the waist, up to 50 % thigh at the hem
        z = P[:, 2]
        t = 0.5 * np.clip((z.max() - z) / max(np.ptp(z), 1e-9), 0, 1)
        sl = 1 / (1 + np.exp(-P[:, 0] / (0.02 * hB)))              # +x = his left
        out[:, gi(roles["root"])] = 1 - t
        out[:, gi(roles["leg_l"]["hip"])] += t * sl
        out[:, gi(roles["leg_r"]["hip"])] += t * (1 - sl)
    else:                                                        # each plate follows the one bone it sits on
        allowed = {"arm": [arm_r["elbow"], arm_r["wrist"]], "gauntlet": [arm_r["wrist"], arm_r["hand"]],
                   "leg": [leg_r["hip"], leg_r["knee"]], "boot": [leg_r["ankle"], leg_r["foot"]]}[base]
        cols = [gi(b) for b in allowed]
        pick = np.array(cols)[np.argmax(Wa[:, cols], 1)]
        out[np.arange(len(P)), pick] = 1
    return out


def load_parts(path, label):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    parts = sorted((o for o in new if o.type == "MESH"), key=lambda o: o.name)
    for o in parts:
        o.data.transform(o.matrix_world)
        o.parent = None
        o.matrix_world = Matrix.Identity(4)
    for o in new:
        if o not in parts:
            bpy.data.objects.remove(o, do_unlink=True)
    # 1. align: one similarity for every part
    A = np.concatenate([world_verts(o) for o in parts])
    s = hB / float(np.ptp(A[:, 2]))
    a0, b0 = box_anchor(A), box_anchor(B)
    A = (A - a0) * s + b0
    shift = np.zeros(3)
    rng = np.random.default_rng(0)
    for _ in range(40):
        hpts = A[A[:, 2] > A[:, 2].max() - HEAD_FRAC * hB]
        hpts = hpts[rng.choice(len(hpts), min(6000, len(hpts)), replace=False)]
        idx, dist = nearest(tree_head, hpts)
        keep = dist[:, 0] < np.percentile(dist[:, 0], 90)
        delta = (head_b[idx[keep, 0]] - hpts[keep]).mean(0)
        A += delta
        shift += delta
        if np.linalg.norm(delta) < 1e-5 * hB:
            break
    log(f"{label}: {len(parts)} parts, scale {s:.4f}, head residual median {np.median(dist[:, 0]) / hB * 100:.2f}% of height")
    # 2. weights per part
    for j, o in enumerate(parts):
        P = (world_verts(o) - a0) * s + b0 + shift
        o.data.vertices.foreach_set("co", P.astype(np.float32).ravel())
        o.data.update()
        idx4, d4 = nearest(tree_body, P, k=4)
        inv = 1.0 / np.maximum(d4, 1e-6)
        Wa = (W[idx4] * inv[:, :, None]).sum(1) / inv.sum(1, keepdims=True)
        if RIGID:
            Wa = rigid_weights(o.name.split(".")[0], P, Wa)
        top = np.argsort(-Wa, 1)[:, :4]
        m4 = np.zeros_like(Wa, bool)
        np.put_along_axis(m4, top, True, 1)
        Wa = np.where(m4, Wa, 0)
        Wa /= np.maximum(Wa.sum(1, keepdims=True), 1e-9)
        for gi, name in enumerate(gnames):
            nz = np.nonzero(Wa[:, gi] > 1e-3)[0]
            if not len(nz):
                continue
            vg = o.vertex_groups.new(name=name)
            q = np.round(Wa[nz, gi] * 255).astype(int)
            for level in np.unique(q):
                vg.add(nz[q == level].tolist(), level / 255.0, "REPLACE")
        o.parent = arm
        o.matrix_parent_inverse = arm.matrix_world.inverted()
        o.modifiers.new("Armature", "ARMATURE").object = arm
        o.color = tuple(x / 255 for x in PALETTE[j % len(PALETTE)]) + (1,)
    return parts


sc = bpy.context.scene
sc.render.engine = "BLENDER_WORKBENCH"
sc.display.shading.light = "STUDIO"
sc.display.shading.color_type = "TEXTURE" if TEXTURE else "OBJECT"
sc.render.resolution_x = sc.render.resolution_y = RES
sc.world = bpy.data.worlds.new("w")
sc.world.color = (0.18, 0.18, 0.2)
if HIDE_BODY:
    body.hide_render = True
    sc.world.color = (0.8, 0.08, 0.08)
    sc.display.shading.show_backface_culling = True
SHOWING = "red = see-through gap" if HIDE_BODY else "green = body showing"
if TEXTURE:                               # judging the look: neutral background
    sc.world.color = (0.3, 0.3, 0.32)
    sc.display.shading.show_specular_highlight = False   # Workbench adds a gloss the paint does not have
    SHOWING = "real paint"
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = hB * 1.25
centre = Vector(((B.min(0) + B.max(0)) / 2).tolist())
VIEWS = {"front": Vector((0, -1, 0)), "3/4": Vector((-0.7, -0.7, 0)), "side": Vector((1, 0, 0)),
         "back": Vector((0, 1, 0))}
al, ar, ll, lr = roles["arm_l"], roles["arm_r"], roles["leg_l"], roles["leg_r"]
POSES = {
    "rest": [],
    "arms up": [(al["elbow"], "Y", -70), (ar["elbow"], "Y", 70)],
    "arms fwd": [(al["elbow"], "X", -70), (ar["elbow"], "X", -70)],
    "twist": [(roles["chest"], "Z", 35)],
    "bend": [(roles["spine"], "X", 30)],
    "step": [(ll["hip"], "X", -40), (ll["knee"], "X", 50), (lr["hip"], "X", 25)],
}


def pose(name):
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()
    M = arm.matrix_world
    for bone, axis, deg in POSES[name]:
        pb = arm.pose.bones[bone]
        h = M @ pb.head
        R = Matrix.Translation(h) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-h)
        pb.matrix = M.inverted() @ R @ M @ pb.matrix
        bpy.context.view_layer.update()


def shot(view, path):
    d = VIEWS[view].normalized()
    cam.location = centre + d * hB * 3
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return Image.open(path).convert("RGB")


variants = {label: load_parts(path, label) for label, path in VARIANTS}
if DQS:
    for o in bpy.data.objects:
        for m in getattr(o, "modifiers", []):
            if m.type == "ARMATURE":
                m.use_deform_preserve_volume = True
if not VARIANTS:                          # no parts given: the bare rigged body alone, in its own paint
    body.hide_render = False
    sc.display.shading.show_backface_culling = False
    variants = {"body": []}
frames = {}
for label, parts in variants.items():
    for other in variants.values():
        for o in other:
            o.hide_render = other is not parts
    tmp = os.path.join(OUT, f"_frames_{label}{'_dqs' if DQS else ''}{'_rigid' if RIGID else ''}")
    os.makedirs(tmp, exist_ok=True)
    for pname in POSES:
        pose(pname)
        for v in VIEWS:
            frames[label, pname, v] = shot(v, os.path.join(tmp, f"{pname}_{v}.png".replace(" ", "_").replace("/", "")))
    log("rendered", label)
    LABEL = 22
    sheet = Image.new("RGB", (RES * len(VIEWS), (RES + LABEL) * len(POSES)), (25, 25, 28))
    draw = ImageDraw.Draw(sheet)
    for r, pname in enumerate(POSES):
        y = r * (RES + LABEL)
        draw.text((6, y + 4), f"{pname} | {label} ({SHOWING})      " + "   ".join(VIEWS), fill=(230, 230, 230))
        for c, v in enumerate(VIEWS):
            sheet.paste(frames[label, pname, v], (c * RES, y + LABEL))
    sheet.save(os.path.join(OUT, f"POSE_{label}{'_nobody' if HIDE_BODY else ''}{'_tex' if TEXTURE else ''}{'_dqs' if DQS else ''}{'_rigid' if RIGID else ''}.png"))

# side by side: each key pose, every variant, front and 3/4
KEY = [("rest", "front"), ("arms up", "front"), ("arms up", "3/4"), ("twist", "3/4"), ("step", "side"), ("bend", "side")]
labels = list(variants)
cmp = Image.new("RGB", (RES * len(labels), (RES + 22) * len(KEY)), (25, 25, 28))
draw = ImageDraw.Draw(cmp)
for r, (pname, v) in enumerate(KEY):
    for c, label in enumerate(labels):
        cmp.paste(frames[label, pname, v], (c * RES, r * (RES + 22) + 22))
        draw.text((c * RES + 6, r * (RES + 22) + 4), f"{label} | {pname} {v}", fill=(230, 230, 230))
cmp.save(os.path.join(OUT, f"POSE_COMPARE{'_nobody' if HIDE_BODY else ''}{'_tex' if TEXTURE else ''}.png"))
pose("rest")
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "pose_test.blend"))
log("POSE_OK")
