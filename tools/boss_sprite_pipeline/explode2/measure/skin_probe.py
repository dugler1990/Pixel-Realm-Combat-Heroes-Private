"""Why does the body show here? Probe a box of pixels of an explode_pose --mask render, at rest.

    .venv-bpy/Scripts/python.exe skin_probe.py <base_rigged.glb> <fit_dir> <view> <label>:<x0,y0,x1,y1> [...]

Same camera as explode_pose (512 px, ortho, framed on the untucked body), the body with fit_dir's tuck applied
and fit_dir/parts_fit.glb as fitted (rest: no weights needed). For every pixel in the box whose ray meets the
body before any armour: the body vertex hit (nearest corner of the face), its main bone, how far the tuck moved
it and in which direction relative to its normal, and the armour piece next behind it along the ray (how far).
Prints counts per main bone and per piece behind, and the tuck numbers.
"""
import os
import sys
from collections import Counter

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "explode"))
from explode_common import world_verts  # noqa: E402

BASE, FIT, VIEW = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3]
BOXES = [(a.split(":")[0], [int(v) for v in a.split(":")[1].split(",")]) for a in sys.argv[4:]]
RES = 512
VIEWS = {"front": (0, -1, 0), "34": (-0.7, -0.7, 0), "side": (1, 0, 0), "back": (0, 1, 0)}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=BASE)
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
B = world_verts(body)
hB = float(np.ptp(B[:, 2]))
centre = Vector(((B.min(0) + B.max(0)) / 2).tolist())
gnames = [g.name for g in body.vertex_groups]
W = np.zeros((len(B), len(gnames)), np.float32)
for v in body.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight
main = W.argmax(1)
t = np.load(os.path.join(FIT, "tuck_offsets.npz"))
d, j = cKDTree(t["rest"]).query(B, workers=-1)
off = np.where((d < 1e-4 * hB)[:, None], t["offset"][j], 0)
Bt = B + off
N = np.empty(len(B) * 3, np.float32)
body.data.vertices.foreach_get("normal", N)
N = N.reshape(-1, 3) @ np.array(body.matrix_world)[:3, :3].T
N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
F = np.array([p.vertices[:] for p in body.data.polygons if len(p.vertices) == 3])
bvh_body = BVHTree.FromPolygons(Bt.tolist(), F.tolist(), all_triangles=True)
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=os.path.join(FIT, "parts_fit.glb"))
pieces, EDGE = {}, {}
for o in [o for o in bpy.data.objects if o not in before and o.type == "MESH"]:
    P = world_verts(o)
    T = np.array([p.vertices[:] for p in o.data.polygons if len(p.vertices) == 3])
    pieces[o.name.split(".")[0]] = BVHTree.FromPolygons(P.tolist(), T.tolist(), all_triangles=True)
    EDGE[o.name.split(".")[0]] = np.linalg.norm(P[T] - P[np.roll(T, 1, 1)], axis=2).max(1) / hB * 100

dv = Vector(VIEWS[VIEW]).normalized()
loc = centre + dv * hB * 3
rot = (-dv).to_track_quat("-Z", "Y").to_matrix()
right, up, fwd = rot.col[0], rot.col[1], -rot.col[2]
s = hB * 1.25


bvh_rest = BVHTree.FromPolygons(B.tolist(), F.tolist(), all_triangles=True)


def sees_out(i):
    """fit_set.py's outer-skin test for body vertex i (at rest, untucked)."""
    n = Vector(N[i].tolist())
    t1 = n.cross(Vector((0, 0, 1)))
    t1 = (t1 if t1.length > 1e-3 else n.cross(Vector((1, 0, 0)))).normalized()
    t2 = n.cross(t1)
    o = Vector(B[i].tolist()) + n * 1e-5 * hB
    return any(bvh_rest.ray_cast(o, d, 3 * hB)[0] is None
               for d in (n, n * 0.5 + t1 * 0.87, n * 0.5 - t1 * 0.87, n * 0.5 + t2 * 0.87, n * 0.5 - t2 * 0.87))


def probe(label, x0, y0, x1, y1):
    bones, behind, rows = Counter(), Counter(), []
    for y in range(y0, y1):
        for x in range(x0, x1):
            o = loc + right * (((x + 0.5) / RES - 0.5) * s) + up * ((0.5 - (y + 0.5) / RES) * s)
            hit = bvh_body.ray_cast(o, fwd)
            if hit[0] is None:
                continue
            db = hit[3]
            arm_hits = [(r[3], n, r[2]) for n, p in pieces.items() for r in [p.ray_cast(o, fwd)]]
            arm_hits = [(dd, n, fi) for dd, n, fi in arm_hits if dd is not None]
            if any(dd < db for dd, _, _ in arm_hits):
                continue                       # armour in front: covered here
            back = min(arm_hits) if arm_hits else (np.inf, "-", None)
            v = F[hit[2]][np.argmin(np.linalg.norm(Bt[F[hit[2]]] - np.array(hit[0]), axis=1))]
            bones[gnames[main[v]]] += 1
            gap = (back[0] - db) / hB * 100
            behind[f"{back[1]} {'<2%' if gap < 2 else '>=2%'}"] += 1
            fn = np.cross(Bt[F[hit[2]][1]] - Bt[F[hit[2]][0]], Bt[F[hit[2]][2]] - Bt[F[hit[2]][0]])
            facing_cam = float(fn @ -np.array(fwd)) > 0         # a face seen from outside faces the camera
            rows.append((float(np.linalg.norm(off[v])) / hB * 100, float(off[v] @ N[v]) / hB * 100, gap,
                         facing_cam, sees_out(v), float(N[v] @ -np.array(fwd)) > 0,
                         EDGE[back[1]][back[2]] if back[2] is not None else np.nan))
    print(f"=== {label} {VIEW} box {x0},{y0}-{x1},{y1}: {len(rows)} body pixels")
    print("  main bone:", ", ".join(f"{k} {v}" for k, v in bones.most_common()))
    print("  armour behind:", ", ".join(f"{k} {v}" for k, v in behind.most_common()))
    if rows:
        R = np.array(rows)
        fin = np.isfinite(R[:, 2])
        print(f"  tuck moved: median {np.median(R[:, 0]):.2f}% h (not moved: {int((R[:, 0] < 1e-3).sum())} px); along "
              f"the normal median {np.median(R[:, 1]):+.2f}% h (outward: {int((R[:, 1] > 1e-3).sum())} px); armour "
              f"behind median {np.median(R[fin, 2]) if fin.any() else float('nan'):.2f}% h")
        print(f"  face wound towards the camera: {int(R[:, 3].sum())} of {len(R)}; vertex normal towards the camera: "
              f"{int(R[:, 5].sum())}; vertex counted as outer skin (fit_set's sees_out): {int(R[:, 4].sum())}")
        e = R[np.isfinite(R[:, 6]), 6]
        if len(e):
            print(f"  longest edge of the armour triangle behind: median {np.median(e):.2f}% h, max {e.max():.2f}% h "
                  f"(over 1% h: {int((e > 1).sum())} px)")


for label, (x0, y0, x1, y1) in BOXES:
    probe(label, x0, y0, x1, y1)
