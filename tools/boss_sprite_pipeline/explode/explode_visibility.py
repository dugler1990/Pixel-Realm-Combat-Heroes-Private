"""How much of the outfit's surface can a camera see at all? Ray casts, not pixels.

    .venv-bpy/Scripts/python.exe explode_visibility.py <outfit.glb> [labels_face.npy parts.json] [--pose roles.json]

--greedy <out.json>: full visibility matrix for the 256 directions, then pick directions one by one,
each time the one that adds the most still-unseen surface; prints the curve and saves the order
(yaw, elev, cumulative %) for explode_render.
--json <out.json>: every setting and number of this run, for explode2/diag.py.
--pose: the GLB must be rigged (explode2/outfit_skeleton.py); measured in the cut pose of
explode2/pose_render.py (arms raised, legs spread) instead of at rest.

Samples points evenly over the surface (by area) and casts a ray from each towards every camera
direction: a point is visible from a direction if the ray leaves the mesh without hitting anything.
No pixels involved, so small faces are not missed (explode_label's DIRECT COVERAGE counts a vertex
only if it is the nearest vertex to some pixel, which under-counts dense meshes).

Direction sets: the 8-view and 96-view cameras of explode_render.py, and 256 directions spread over
the whole sphere (the ceiling for any outside camera with the figure in this pose). Points hidden from
all 256 are enclosed: armour insides, the body under the armour, deep creases.
With labels_face.npy + parts.json (explode_label output): the hidden share per part.
"""
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

FLAGS = ("--pose", "--greedy", "--json")
opt = {f: sys.argv[sys.argv.index(f) + 1] for f in FLAGS if f in sys.argv}
POSE, GREEDY, JSON_OUT = opt.get("--pose"), opt.get("--greedy"), opt.get("--json")
ARGV = [a for i, a in enumerate(sys.argv) if a not in FLAGS and (i == 0 or sys.argv[i - 1] not in FLAGS)]
GLB = ARGV[1]
N = 20000
rng = np.random.default_rng(0)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
mesh = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
if POSE:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "explode2"))
    from pose_render import apply_pose, cut_pose
    apply_pose(next(o for o in bpy.data.objects if o.type == "ARMATURE"), cut_pose(json.load(open(POSE))))
    me = bpy.data.meshes.new_from_object(mesh.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    print("measured in the cut pose", flush=True)
else:
    me = mesh.data
me.calc_loop_triangles()
co = np.empty(len(me.vertices) * 3, np.float32)
me.vertices.foreach_get("co", co)
m = np.array(mesh.matrix_world)
V = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
h = float(np.ptp(V[:, 2]))
T = np.empty(len(me.loop_triangles) * 3, np.int64)
me.loop_triangles.foreach_get("vertices", T)
T = T.reshape(-1, 3)
TP = np.empty(len(me.loop_triangles), np.int64)
me.loop_triangles.foreach_get("polygon_index", TP)
bvh = BVHTree.FromPolygons(V.tolist(), T.tolist(), all_triangles=True)

a, b, c = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
pick = rng.choice(len(T), N, p=area / area.sum())
u, v = rng.random(N), rng.random(N)
flip = u + v > 1
u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
P = a[pick] + u[:, None] * (b[pick] - a[pick]) + v[:, None] * (c[pick] - a[pick])


def cam_dir(yaw, elev):
    y, e = math.radians(yaw), math.radians(elev)
    return (math.sin(y) * math.cos(e), -math.cos(y) * math.cos(e), math.sin(e))


k = np.arange(256) + 0.5
z = 1 - 2 * k / 256
r = np.sqrt(1 - z * z)
phi = k * math.pi * (3 - math.sqrt(5))
SETS = {
    "8 views": [cam_dir(y, 10) for y in (0, 90, 180, 270)],
    "96 views": [cam_dir(y, e) for e in (-30, 0, 25, 55) for y in range(0, 360, 30)],
    "256 dirs (any outside camera)": list(zip(r * np.cos(phi), r * np.sin(phi), z)),
}
eps = 1e-5 * h
far = 3 * h
seen = {}
for name, dirs in SETS.items():
    D = [Vector(d).normalized() for d in dirs]
    s = np.zeros(N, bool)
    for i, p in enumerate(P):
        p = Vector(p)
        for d in D:
            if bvh.ray_cast(p + d * eps, d, far)[0] is None:
                s[i] = True
                break
    seen[name] = s
    print(f"VISIBLE from {name}: {100 * s.mean():.1f}% of the surface area", flush=True)
DIAG = {"step": "coverage", "glb": GLB, "pose": "cut pose" if POSE else "rest",
        "settings": {"sample_points": N, "ray_offset_h": 1e-5, "direction_sets": {k: len(v) for k, v in SETS.items()}},
        "results": {"visible_pct": {k: round(100 * float(v.mean()), 2) for k, v in seen.items()}}}

hidden = ~seen["256 dirs (any outside camera)"]
if GREEDY:
    D = [Vector(d).normalized() for d in SETS["256 dirs (any outside camera)"]]
    vis = np.zeros((len(D), N), bool)
    for i, p in enumerate(P):
        if hidden[i]:
            continue
        p = Vector(p)
        for j, d in enumerate(D):
            vis[j, i] = bvh.ray_cast(p + d * eps, d, far)[0] is None
    got = np.zeros(N, bool)
    order = []
    for _ in range(len(D)):
        gain = (vis & ~got).sum(1)
        j = int(np.argmax(gain))
        if gain[j] == 0:
            break
        got |= vis[j]
        d = D[j]
        order.append({"yaw": round(math.degrees(math.atan2(d.x, -d.y)), 1),
                      "elev": round(math.degrees(math.asin(max(-1, min(1, d.z)))), 1),
                      "cum": round(100 * got.mean(), 2)})
    for k in (4, 8, 12, 16, 24, 32, 48, 64, 96, 128):
        if k <= len(order):
            print(f"greedy {k:3d} directions: {order[k - 1]['cum']:.1f}% of the surface "
                  f"({100 * order[k - 1]['cum'] / (100 * (~hidden).mean()):.1f}% of the visible ceiling)", flush=True)
    json.dump(order, open(GREEDY, "w"), indent=1)
    DIAG["results"]["greedy_pct_by_count"] = {k: order[k - 1]["cum"] for k in (4, 8, 12, 16, 24, 32, 48, 64, 96, 128) if k <= len(order)}
    DIAG["results"]["greedy_file"] = GREEDY
if len(ARGV) > 3:
    lab = np.load(ARGV[2])
    parts = json.load(open(ARGV[3]))["parts"]
    fl = lab[TP[pick]]
    print("hidden from every outside direction, by part (share of that part's area):")
    for j, p in enumerate(parts):
        sel = fl == j
        if sel.any():
            print(f"  {p:12s} {100 * hidden[sel].mean():5.1f}%   ({100 * sel.mean():.1f}% of all area)")
            DIAG["results"].setdefault("hidden_pct_by_part", {})[p] = round(100 * float(hidden[sel].mean()), 1)
if JSON_OUT:
    json.dump(DIAG, open(JSON_OUT, "w"), indent=1)
print("VIS_OK")
