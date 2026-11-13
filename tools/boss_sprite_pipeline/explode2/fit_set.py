"""Fit a set of worn pieces to the body and tuck the skin under them, in every fit pose (steps 11-12, any piece).

    .venv-bpy/Scripts/python.exe fit_set.py <base_rigged.glb> <roles.json> <parts.glb> <out_dir>
        [--only a,b,...] [--gap 0.005] [--margin 0.004] [--diag <file>]

World space, pose by pose (explode_common.fit_poses: the 6 test poses and the 8 stretch extremes), for any
piece shape, rigid or blended (explode_common.piece_weights, the weights explode_pose --rigid uses).
Everything is a height above the skin: a point's nearest body vertex in that pose and its outward normal,
height = (point - skin) . normal.

1. Fit, inner pieces first (ORDER). A piece vertex must stand GAP above the skin, and GAP above any piece
   already fitted under it (the inner piece's heights over the same skin, within LATERAL). The shortfall, the
   worst over the poses, is spread to every vertex of the piece within SPREAD (so all layers of a plate move
   together and it keeps its thickness), smoothed over the mesh, and the piece is pushed out along the skin's
   rest normal. Only outward.
2. Tuck. Each skin vertex on the bones the worn pieces cover (skin_bones) must stay MARGIN below the lowest
   piece surface over it (piece vertices within LATERAL of its normal line) in every pose; it is pushed in
   along its rest normal by the shortfall, spread and smoothed so the patch has no step. Skin no piece covers
   does not move, so the body keeps no holes.

Writes <out_dir>/parts_fit.glb (every part of parts.glb; the worn ones fitted; materials double-sided so thin
plates keep their undersides in a game), body_tucked.glb (the base with its tucked rest shape, same rig),
tuck_offsets.npz (rest position -> offset per skin vertex) and fit_set.json. Render with
explode_pose.py --texture --aligned --rigid --tuck-from tuck_offsets.npz <base or animated.blend> ... worn=parts_fit.glb.
"""
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "explode"))
from explode_common import PAULDRON_ARM, fit_poses, piece_weights, set_pose, skin_bones, world_verts  # noqa: E402

argv = sys.argv[1:]
opt = {}
for f in ("--only", "--gap", "--margin", "--diag"):
    if f in argv:
        i = argv.index(f)
        opt[f] = argv[i + 1]
        del argv[i:i + 2]
BASE, ROLES, PARTS, OUT = (os.path.abspath(a) for a in argv[:4])
ONLY = set(opt["--only"].split(",")) if "--only" in opt else None
GAP, MARGIN = float(opt.get("--gap", 0.005)), float(opt.get("--margin", 0.004))
SPREAD, LATERAL, NEAR = 0.012, 0.012, 0.08      # x height
ORDER = ["leg_l", "leg_r", "boot_l", "boot_r", "arm_l", "arm_r", "gauntlet_l", "gauntlet_r",
         "torso", "belt", "skirt", "pauldron_l", "pauldron_r", "head"]
DIAG_OUT = os.path.abspath(opt["--diag"]) if "--diag" in opt else None
os.makedirs(OUT, exist_ok=True)
t0 = time.time()


def log(*a):
    print(*a, flush=True)


# --- base ----------------------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=BASE)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
for o in [o for o in bpy.data.objects if o.type == "MESH" and o is not body]:
    bpy.data.objects.remove(o, do_unlink=True)
roles = json.load(open(ROLES))
POSES = fit_poses(roles)
gnames = [g.name for g in body.vertex_groups]
nB = len(body.data.vertices)
W = np.zeros((nB, len(gnames)), np.float32)
for v in body.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
mainB = W.argmax(1)
bmw = np.array(body.matrix_world)


def body_posed():
    """World positions and unit normals of the body in the current pose."""
    ev = body.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    no = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("normal", no)
    ev.to_mesh_clear()
    X = co.reshape(-1, 3) @ bmw[:3, :3].T + bmw[:3, 3]
    N = no.reshape(-1, 3) @ bmw[:3, :3].T
    return X, N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)


set_pose(arm, [])
B0, N0 = body_posed()
h = float(np.ptp(B0[:, 2]))
FB = np.array([p.vertices[:] for p in body.data.polygons if len(p.vertices) == 3])
EB = np.concatenate([FB[:, [0, 1]], FB[:, [1, 2]], FB[:, [2, 0]]])
# The body is a shell: an outer skin and an inner layer whose normals point into the body (barb_final: half
# the vertex normals across the chest). Only the outer skin counts as skin; a vertex is on it when a ray along
# its normal leaves the body. (Without this the inner layer read as skin: heights came out negative, the fit
# pushed nearly everything and the tuck moved the inner layer out through the skin, 2026-11-03.)
from mathutils import Vector  # noqa: E402
from mathutils.bvhtree import BVHTree  # noqa: E402
_bvh = BVHTree.FromPolygons(B0.tolist(), FB.tolist(), all_triangles=True)


def sees_out(p, n):
    """Outer skin can see out of the body in some direction round its normal (armpit skin's straight-out
    ray hits the arm, but a tilted one escapes); the inner layer faces an enclosed cavity and never does."""
    n = Vector(n)
    t1 = n.cross(Vector((0, 0, 1)))
    t1 = (t1 if t1.length > 1e-3 else n.cross(Vector((1, 0, 0)))).normalized()
    t2 = n.cross(t1)
    o = Vector(p) + n * 1e-5 * h
    return any(_bvh.ray_cast(o, d, 3 * h)[0] is None
               for d in (n, n * 0.5 + t1 * 0.87, n * 0.5 - t1 * 0.87, n * 0.5 + t2 * 0.87, n * 0.5 - t2 * 0.87))


OUTER = np.array([sees_out(p, n) for p, n in zip(B0, N0)])
oi = np.nonzero(OUTER)[0]
log(f"body: {len(B0)} verts, outer skin {len(oi)} ({100 * OUTER.mean():.1f}%), inner layer {int((~OUTER).sum())}")
tree0 = cKDTree(B0[oi])                   # rest outer skin: nearest-skin lookups go to the outer layer only
_, inner_to_outer = tree0.query(B0[~OUTER], workers=-1)


def bone_mats():
    """Per bone: current world matrix x rest world matrix^-1 (the linear-blend skinning transform)."""
    return {g: np.array(arm.matrix_world @ arm.pose.bones[g].matrix) for g in gnames if g in arm.pose.bones}


set_pose(arm, [])
REST = {g: np.linalg.inv(M) for g, M in bone_mats().items()}

# --- parts -----------------------------------------------------------------------------------------
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=PARTS)
parts = {o.name.split(".")[0]: o for o in bpy.data.objects if o not in before and o.type == "MESH"}
for o in [o for o in bpy.data.objects if o not in before and o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
for o in parts.values():
    o.data.transform(o.matrix_world)
    o.matrix_world = Matrix.Identity(4)
worn = [p for p in ORDER if p in parts and (ONLY is None or p in ONLY)]
log(f"worn, inner first: {', '.join(worn)}")
PIECE = {}
for name in worn:
    o = parts[name]
    P = world_verts(o)
    d4, i4 = tree0.query(P, k=4, workers=-1)
    inv = 1.0 / np.maximum(d4, 1e-6)
    Wa = (W[oi[i4]] * inv[:, :, None]).sum(1) / inv.sum(1, keepdims=True)
    Wp = piece_weights(name, P, Wa, roles, gnames, h)
    cols = np.nonzero(Wp.sum(0) > 0)[0]
    F = np.array([p.vertices[:] for p in o.data.polygons if len(p.vertices) == 3])
    PIECE[name] = {"P": P, "W": Wp[:, cols], "bones": [gnames[c] for c in cols], "F": F}


def lbs(name, P, mats):
    """A piece's vertices in the current pose (its weights over its few bones)."""
    pc = PIECE[name]
    out = np.zeros_like(P)
    Ph = np.c_[P, np.ones(len(P))]
    for k, b in enumerate(pc["bones"]):
        M = mats[b] @ REST[b]
        w = pc["W"][:, k]
        sel = w > 0
        out[sel] += w[sel, None] * (Ph[sel] @ M.T)[:, :3]
    return out


def spread_max(P, need, cell):
    """Every vertex takes the largest need within ~one cell of it (a voxel grid max over 27 cells)."""
    key = np.floor(P / cell).astype(np.int64)
    k0 = key - key.min(0)
    dims = k0.max(0) + 3
    flat = lambda k: (k[:, 0] * dims[1] + k[:, 1]) * dims[2] + k[:, 2]
    cells, inv = np.unique(flat(k0 + 1), return_inverse=True)
    cmax = np.zeros(len(cells))
    np.maximum.at(cmax, inv, need)
    lut = dict(zip(cells.tolist(), cmax.tolist()))
    out = need.copy()
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                nk = flat(k0 + 1 + np.array([dx, dy, dz]))
                out = np.maximum(out, np.array([lut.get(x, 0.0) for x in nk.tolist()]))
    return out


def smooth(vals, E, n, iters):
    deg = np.bincount(E[:, 0], minlength=n) + np.bincount(E[:, 1], minlength=n)
    for _ in range(iters):
        s = np.bincount(E[:, 0], weights=vals[E[:, 1]], minlength=n) + \
            np.bincount(E[:, 1], weights=vals[E[:, 0]], minlength=n)
        vals = 0.5 * vals + 0.5 * s / np.maximum(deg, 1)
    return vals


def heights(X, Xb, Nb, treeb):
    """Height of points X above the posed skin (nearest body vertex, its normal) and that vertex's index."""
    _, idx = treeb.query(X, workers=-1)
    return ((X - Xb[idx]) * Nb[idx]).sum(1), idx


# per pose, once: the posed outer skin, its tree, bone matrices
POSED = {}
for pname, rots in POSES.items():
    set_pose(arm, rots)
    Xb, Nb = body_posed()
    Xb, Nb = Xb[oi], Nb[oi]
    POSED[pname] = (Xb, Nb, cKDTree(Xb), bone_mats())
    log(f"pose {pname}")
set_pose(arm, [])

# --- 1. fit, inner first -----------------------------------------------------------------------------
report = {"poses": list(POSES), "gap_h": GAP, "margin_h": MARGIN, "pauldron_arm": PAULDRON_ARM, "pieces": {}}
fitted = []
for name in worn:
    pc = PIECE[name]
    P = pc["P"]
    need = np.zeros(len(P))
    for pname, (Xb, Nb, treeb, mats) in POSED.items():
        X = lbs(name, P, mats)
        hg, _ = heights(X, Xb, Nb, treeb)
        short = GAP * h - hg
        for inner in fitted:                     # stand GAP above every piece already fitted under it
            Y = lbs(inner, PIECE[inner]["P"], mats)
            hy, _ = heights(Y, Xb, Nb, treeb)
            d, j = cKDTree(Y).query(X, workers=-1)
            over = d < LATERAL * h
            short = np.where(over, np.maximum(short, hy[j] + GAP * h - hg), short)
        need = np.maximum(need, short)
    raw = np.maximum(need, 0)
    push = spread_max(P, raw, SPREAD * h)
    E = np.concatenate([pc["F"][:, [0, 1]], pc["F"][:, [1, 2]], pc["F"][:, [2, 0]]])
    push = np.maximum(smooth(push, E, len(P), 4), 0.8 * raw)
    _, i0 = tree0.query(P, workers=-1)
    pc["P"] = P + N0[oi[i0]] * push[:, None]
    fitted.append(name)
    report["pieces"][name] = {"verts_short": int((raw > 0).sum()), "verts": len(P),
                              "push_max_pct_h": round(100 * float(push.max()) / h, 2),
                              "push_median_pushed_pct_h": round(100 * float(np.median(push[push > 1e-9])) / h, 2)
                              if (push > 1e-9).any() else 0.0, "bones": pc["bones"]}
    log(f"fit {name:11s}: {int((raw > 0).sum())} of {len(P)} verts too close in some pose; push max "
        f"{100 * push.max() / h:.2f}% h")

# --- 2. tuck -----------------------------------------------------------------------------------------
covered_names = {b for n in worn for b in skin_bones(n, roles)}
for side in ("l", "r"):                  # fingers and toes have no role: they go with the hand / foot they hang from
    for b in (roles[f"arm_{side}"]["hand"], roles[f"leg_{side}"]["foot"]):
        if b in covered_names and b in arm.data.bones:
            covered_names |= {c.name for c in arm.data.bones[b].children_recursive}
covered_bones = {gnames.index(b) for b in covered_names if b in gnames}
log(f"tuck: skin on {len(covered_bones)} bones ({', '.join(sorted(covered_names, key=lambda s: int(s.split('_')[-1]) if s.split('_')[-1].isdigit() else 0))})")
allP = np.concatenate([PIECE[n]["P"] for n in worn])
dnear, _ = cKDTree(allP).query(B0[oi], workers=-1)
cand = np.nonzero(np.isin(mainB[oi], list(covered_bones)) & (dnear < NEAR * h))[0]   # indices into the outer skin
# Search the skin's normal line for armour from DEEP below to MARGIN above (only armour lower than MARGIN asks for
# a push): sample points along it, take the armour vertices nearest each, keep those within LATERAL of the line.
# (The 32 armour vertices nearest the skin point alone all sat on the closest plate edge - the tasset beside the
# loincloth - so the plate right behind it was never seen and the skin was left in front of it, 2026-11-04.)
DEEP, KS = 0.03, 8
T_SAMPLES = np.arange(-DEEP, MARGIN + 1e-9, LATERAL / 2)


def lowest_armour(s, n, Y, Yn, treeY):
    """Per skin point (s, unit normal n): height of the lowest armour over it along its normal line, inf if none.
    Yn: per armour point, the normal of the skin it sits over (its nearest outer skin vertex). Armour over the
    other side of a thin part does not count: searched 3 % h deep, a finger's front skin found the gauntlet's
    back plate and was pushed through the finger and out of the gauntlet (2026-11-04)."""
    low = np.full(len(s), np.inf)
    for t in T_SAMPLES:
        _, j = treeY.query(s + t * h * n, k=KS, workers=-1)
        rel = Y[j] - s[:, None, :]
        hgt = (rel * n[:, None, :]).sum(2)
        lat = np.linalg.norm(rel - hgt[:, :, None] * n[:, None, :], axis=2)
        ok = (lat < LATERAL * h) & (hgt > -DEEP * h) & ((Yn[j] * n[:, None, :]).sum(2) > 0)
        low = np.minimum(low, np.where(ok, hgt, np.inf).min(1))
    return low


tneed_o = np.zeros(len(oi))
for pname, (Xb, Nb, treeb, mats) in POSED.items():
    Y = np.concatenate([lbs(n, PIECE[n]["P"], mats) for n in worn])
    lowest = lowest_armour(Xb[cand], Nb[cand], Y, Nb[treeb.query(Y, workers=-1)[1]], cKDTree(Y))
    short = np.where(np.isfinite(lowest), MARGIN * h - lowest, 0)
    tneed_o[cand] = np.maximum(tneed_o[cand], short)
    log(f"tuck {pname}: {int((short > 0).sum())} skin verts too close / poking out")
# Push direction: in along the rest normal, except where the normal faces the bone - the back face of a thin flap
# (the loincloth): along its own normal it was pushed forward, through the front face and out past the skirt
# (2026-11-04). There: towards the main bone's segment, so both faces of the flap go in the same way.
bone_seg = np.zeros((len(gnames), 2, 3))
for gi_, g in enumerate(gnames):
    if g in arm.data.bones:
        bn = arm.data.bones[g]
        bone_seg[gi_] = [np.array(arm.matrix_world @ bn.head_local), np.array(arm.matrix_world @ bn.tail_local)]
a_, b_ = bone_seg[mainB, 0], bone_seg[mainB, 1]
ab = b_ - a_
tt = np.clip(((B0 - a_) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
RAD = B0 - (a_ + tt[:, None] * ab)
RAD /= np.maximum(np.linalg.norm(RAD, axis=1, keepdims=True), 1e-12)
flap = (N0 * RAD).sum(1) < 0
DIR = np.where(flap[:, None], RAD, N0)
log(f"tuck: {int(flap[oi].sum())} outer skin verts face their bone (flap backs), pushed towards it")
# a flap's back finds no armour of its own (it faces the body): it moves as far as the front face across from it,
# else the front face goes behind the armour and leaves the back face in front
fo = flap[oi]
if fo.any() and (~fo).any():
    _, fr = cKDTree(B0[oi[~fo]]).query(B0[oi[fo]], workers=-1)
    tneed_o[fo] = np.maximum(tneed_o[fo], tneed_o[np.nonzero(~fo)[0][fr]])
# the whole shell moves together: each inner-layer vertex takes its nearest outer vertex's push and direction
tneed = np.zeros(nB)
tneed[oi] = np.maximum(tneed_o, 0)
tneed[~OUTER] = tneed[oi[inner_to_outer]]
DIR[~OUTER] = DIR[oi[inner_to_outer]]
traw = tneed.copy()
for _ in range(3):                                                  # grow, then smooth: no step at the edge
    m2 = tneed.copy()
    np.maximum.at(m2, EB[:, 0], tneed[EB[:, 1]])
    np.maximum.at(m2, EB[:, 1], tneed[EB[:, 0]])
    tneed = m2
# never below a vertex's own need: averaging alone thinned the push on small spots (shin, fingertips) until they
# stayed in front of the plate (2026-11-04)
tneed = np.maximum(smooth(tneed, EB, nB, 6), traw)
Bt = B0 - DIR * tneed[:, None]
# the tuck as rest position -> offset: explode_pose.py --tuck-from applies it to any copy of this body (an
# animated.blend from retarget_bvh.py) by position, since a glTF round trip renumbers / splits vertices
np.savez(os.path.join(OUT, "tuck_offsets.npz"), rest=B0.astype(np.float32), offset=(Bt - B0).astype(np.float32))
bmi = np.linalg.inv(bmw)
body.data.vertices.foreach_set("co", (Bt @ bmi[:3, :3].T + bmi[:3, 3]).astype(np.float32).ravel())
body.data.update()
moved = tneed > 1e-5 * h
report["tuck"] = {"candidates": int(len(cand)), "verts_short": int((traw > 0).sum()), "verts_moved": int(moved.sum()),
                  "push_max_pct_h": round(100 * float(tneed.max()) / h, 2), "flap_verts": int(flap[oi].sum())}
log(f"tuck: {int(moved.sum())} skin verts pushed in, max {100 * tneed.max() / h:.2f}% h")
# check: the tucked body posed again, the same search - covered skin still in front of the armour over it
report["tuck"]["still_in_front"] = {}
for pname, rots in POSES.items():
    set_pose(arm, rots)
    Xt, Nt = body_posed()
    mats = POSED[pname][3]
    Y = np.concatenate([lbs(n, PIECE[n]["P"], mats) for n in worn])
    Xo, No = Xt[oi], Nt[oi]
    low = lowest_armour(Xo[cand], No[cand], Y, No[cKDTree(Xo).query(Y, workers=-1)[1]], cKDTree(Y))
    report["tuck"]["still_in_front"][pname] = int(((low < 0) & ~flap[oi[cand]]).sum())   # a flap back faces in
set_pose(arm, [])
log("tuck check, skin still in front of armour: " + ", ".join(f"{k} {v}" for k, v in report["tuck"]["still_in_front"].items()))

# --- write ----------------------------------------------------------------------------------------
for name in worn:
    o = parts[name]
    o.data.vertices.foreach_set("co", PIECE[name]["P"].astype(np.float32).ravel())
    o.data.update()
for o in parts.values():
    for m in o.data.materials:
        if m is not None:
            m.use_backface_culling = False          # glTF doubleSided: thin plates keep their undersides
bpy.ops.object.select_all(action="DESELECT")
for o in parts.values():
    o.select_set(True)
bpy.context.view_layer.objects.active = next(iter(parts.values()))
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "parts_fit.glb"), use_selection=True)
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "body_tucked.glb"), use_selection=True)
report["seconds"] = round(time.time() - t0)
json.dump(report, open(os.path.join(OUT, "fit_set.json"), "w"), indent=1)
if DIAG_OUT:
    json.dump({"step": "11-12 fit_set (fit every worn piece, tuck the skin)", "base": BASE, "glb": PARTS, "out": OUT,
               "settings": {"worn": worn, "gap_h": GAP, "margin_h": MARGIN, "spread_h": SPREAD, "lateral_h": LATERAL,
                            "poses": list(POSES)},
               "results": {"tuck": report["tuck"], **{k: {kk: vv for kk, vv in v.items() if kk != "bones"}
                                                       for k, v in report["pieces"].items()}}},
              open(DIAG_OUT, "w"), indent=1)
log(f"FIT_SET_OK {report['seconds']} s")
