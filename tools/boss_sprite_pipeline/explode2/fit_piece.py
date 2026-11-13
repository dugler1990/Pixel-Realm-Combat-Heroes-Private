"""Step 12: widen a rigid torso piece until the body stays inside it in every test pose.

    .venv-bpy/Scripts/python.exe fit_piece.py <base_rigged.glb> <roles.json> <parts.glb> <part> <out_parts.glb>
                                              [--bone chest] [--gap 0.005] [--thick 0.004] [--diag <file>]

The piece rides one bone rigidly (--bone, a roles.json key; the breastplate: chest), so the body is
looked at from that bone: in each test and stretch pose (explode_common.fit_poses) the body is moved into the bone's
rest frame, where the piece never moves. Around a vertical axis through the piece, both are binned by
height (1 % h) and direction (5 deg): per bin the body's largest radius over all poses (only skin on the
bones the piece sits on: spine, chest, neck, shoulders - not the arms) and the piece's outer radius.
Where the body comes closer than gap + thick to the piece's outside, the piece is pushed outward by the
shortfall; the push is smoothed over neighbouring bins and the same push moves every layer of the piece
in a bin, so the plate keeps its thickness and shape. Only outward, never inward.
Writes <out_parts.glb> (every part, this one fitted, same materials), FIT_<part>.png (horizontal slices:
body over all poses, piece before / after) and the settings + numbers to --diag.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "explode"))
from explode_common import fit_poses, set_pose, world_verts  # noqa: E402

argv = sys.argv[1:]
opt = {}
for f in ("--bone", "--gap", "--thick", "--diag"):
    if f in argv:
        i = argv.index(f)
        opt[f] = argv[i + 1]
        del argv[i:i + 2]
BASE, ROLES, PARTS, PART, OUT = (os.path.abspath(a) if i != 3 else a for i, a in enumerate(argv[:5]))
BONE_ROLE = opt.get("--bone", "chest")
GAP, THICK = float(opt.get("--gap", 0.005)), float(opt.get("--thick", 0.004))
DZ, NAZ = 0.01, 72                       # bin height (x h), direction bins (5 deg)
SMOOTH = (1.5, 1.5)                      # gaussian sigma in bins (height, direction)
DIAG_OUT = os.path.abspath(opt["--diag"]) if "--diag" in opt else None


def log(*a):
    print(*a, flush=True)


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=BASE)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not body]:
    bpy.data.objects.remove(o, do_unlink=True)
roles = json.load(open(ROLES))
B0 = world_verts(body)
h = float(np.ptp(B0[:, 2]))
gnames = [g.name for g in body.vertex_groups]
W = np.zeros((len(B0), len(gnames)), np.float32)
for v in body.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
main = np.array(gnames)[W.argmax(1)]
torso_bones = {roles[k] for k in ("root", "spine", "spine2", "chest", "neck")} | \
              {roles["arm_l"]["shoulder"], roles["arm_r"]["shoulder"]}
skin = np.isin(main, list(torso_bones))
bone = roles[BONE_ROLE]

before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=PARTS)
parts = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
piece = next(o for o in parts if o.name.split(".")[0] == PART)
P = world_verts(piece)


def bone_matrix():
    return np.array(arm.matrix_world @ arm.pose.bones[bone].matrix)


def body_now():
    dg = bpy.context.evaluated_depsgraph_get()
    ev = body.evaluated_get(dg)
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    ev.to_mesh_clear()
    m = np.array(body.matrix_world)
    return co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]


set_pose(arm, [])
C_rest = bone_matrix()
clouds = []
for name, rots in fit_poses(roles).items():
    set_pose(arm, rots)
    X = body_now()[skin]
    T = C_rest @ np.linalg.inv(bone_matrix())          # posed world -> the bone's rest frame
    clouds.append(X @ T[:3, :3].T + T[:3, 3])
    log(f"pose {name}: {len(X)} torso skin verts")
set_pose(arm, [])
Bp = np.concatenate(clouds)

# cylinder bins around a vertical axis through the piece
ax = (P[:, :2].min(0) + P[:, :2].max(0)) / 2
z0 = float(min(P[:, 2].min(), Bp[:, 2].min()))
NZ = int(math.ceil((max(P[:, 2].max(), Bp[:, 2].max()) - z0) / (DZ * h))) + 1


def cyl(X):
    d = X[:, :2] - ax
    r = np.linalg.norm(d, axis=1)
    az = (np.arctan2(d[:, 1], d[:, 0]) + math.pi) / (2 * math.pi) * NAZ
    zi = np.clip(((X[:, 2] - z0) / (DZ * h)).astype(int), 0, NZ - 1)
    return r, az, zi, d / np.maximum(r, 1e-9)[:, None]


rb, azb, zb, _ = cyl(Bp)
rp, azp, zp, dirp = cyl(P)
body_r = np.zeros((NZ, NAZ))
np.maximum.at(body_r, (zb, azb.astype(int) % NAZ), rb)
piece_r = np.zeros((NZ, NAZ))
np.maximum.at(piece_r, (zp, azp.astype(int) % NAZ), rp)
has = piece_r > 0
need = np.where(has, np.maximum(0, body_r + (GAP + THICK) * h - piece_r), 0)
# smooth (wrapping round the body), never below the raw need in a bin that needs it most
pad = np.concatenate([need[:, -4:], need, need[:, :4]], 1)
sm = gaussian_filter(pad, SMOOTH)[:, 4:-4]
push_grid = np.maximum(sm, 0.8 * need)
# per vertex: bilinear in direction, its own height bin
a0 = np.floor(azp - 0.5).astype(int)
t = (azp - 0.5) - a0
push = (1 - t) * push_grid[zp, a0 % NAZ] + t * push_grid[zp, (a0 + 1) % NAZ]
P2 = P.copy()
P2[:, :2] += dirp * push[:, None]
log(f"{PART}: {int((need > 0).sum())} of {int(has.sum())} bins too tight; push max {push.max() / h * 100:.2f}% h, "
    f"median of pushed verts {np.median(push[push > 1e-9]) / h * 100 if (push > 1e-9).any() else 0:.2f}% h")

# still poking through after the push? (bins: body radius vs new outer radius - thickness - gap)
rp2, azp2, zp2, _ = cyl(P2)
piece_r2 = np.zeros((NZ, NAZ))
np.maximum.at(piece_r2, (zp2, azp2.astype(int) % NAZ), rp2)
left = (piece_r2 > 0) & (body_r + (GAP + THICK) * h > piece_r2 + 1e-6)
log(f"after: {int(left.sum())} bins still tighter than gap + thickness")

mw_inv = np.linalg.inv(np.array(piece.matrix_world))
local = P2 @ mw_inv[:3, :3].T + mw_inv[:3, 3]
piece.data.vertices.foreach_set("co", local.astype(np.float32).ravel())
piece.data.update()
bpy.ops.object.select_all(action="DESELECT")
for o in parts:
    o.select_set(True)
bpy.context.view_layer.objects.active = piece
body.hide_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, use_selection=True)
log("exported", OUT)

# --- slices: body over all poses (grey dots), piece before (red) and after (green) --------------
try:
    font = ImageFont.truetype("arial.ttf", 18)
except OSError:
    font = ImageFont.load_default()
zs = np.linspace(P[:, 2].min() + 0.15 * np.ptp(P[:, 2]), P[:, 2].max() - 0.15 * np.ptp(P[:, 2]), 4)
S = 420
sheet = Image.new("RGB", (S * len(zs), S + 30), (250, 250, 250))
d = ImageDraw.Draw(sheet)
span = float(max(np.ptp(P2[:, 0]), np.ptp(P2[:, 1]))) * 1.2
for i, z in enumerate(zs):
    sl = 0.004 * h

    def pts(X, colour, r=1):
        sel = np.abs(X[:, 2] - z) < sl
        for x, y in X[sel][:, :2][:: max(1, int(sel.sum() / 4000))]:
            u = i * S + S / 2 + (x - ax[0]) / span * S
            v = 30 + S / 2 - (y - ax[1]) / span * S
            d.ellipse((u - r, v - r, u + r, v + r), fill=colour)
    pts(Bp, (150, 150, 150))
    pts(P, (220, 30, 30), 1)
    pts(P2, (20, 160, 40), 1)
    d.text((i * S + 8, 6), f"height {100 * (z - B0[:, 2].min()) / h:.0f}% (front is down)", fill=(20, 20, 20), font=font)
sheet.save(os.path.join(os.path.dirname(OUT), f"FIT_{PART}.png"))
if DIAG_OUT:
    json.dump({"step": "12 fit (piece widened to clear the body in every pose)", "base": BASE, "glb": PARTS, "out": OUT,
               "settings": {"part": PART, "bone": f"{BONE_ROLE} ({bone})", "gap_h": GAP, "thick_h": THICK,
                            "bin_height_h": DZ, "direction_bins": NAZ, "smooth_bins": SMOOTH,
                            "poses": list(fit_poses(roles)), "skin_bones": sorted(torso_bones)},
               "results": {"bins_too_tight": int((need > 0).sum()), "bins_with_piece": int(has.sum()),
                           "push_max_pct_h": round(float(push.max() / h * 100), 2),
                           "bins_still_tight": int(left.sum())}}, open(DIAG_OUT, "w"), indent=1)
log("FIT_OK")
