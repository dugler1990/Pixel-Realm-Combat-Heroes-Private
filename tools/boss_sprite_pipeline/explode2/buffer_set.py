"""Grow each worn piece evenly by a measured buffer so the skin under it is covered. No bending, no tuck.

    .venv-bpy/Scripts/python.exe buffer_set.py <base_rigged.glb> <roles.json> <parts.glb> <out_dir>
        [--only a,b,...] [--cover 98] [--margin 0.001] [--cap 0.02]

At rest. Skin under a piece: a 1-in-4 sample (seeded) of the body's outer skin on the piece's bones
(explode_common.skin_bones) within 3 % h of the piece. A skin point is covered when a ray out along its normal
leaves the piece (hits an outward-facing piece face) within 3 % h; otherwise it needs the piece to grow by its
distance to the piece's surface + --margin. The piece's buffer is the --cover percentile of that need over its
skin (covered skin needs 0), capped at --cap (x h). Every piece vertex then moves by the buffer along its own normal,
turned to face away from the nearest skin, so both layers of a plate move out together and it keeps its thickness
and shape. Writes <out_dir>/parts_buffer.glb (every part; worn ones grown; materials double-sided) and buffer.json.
"""
import json
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "explode"))
from explode_common import skin_bones  # noqa: E402

argv = sys.argv[1:]
opt = {}
for f in ("--only", "--cover", "--margin", "--cap"):
    if f in argv:
        i = argv.index(f)
        opt[f] = argv[i + 1]
        del argv[i:i + 2]
BASE, ROLES, PARTS, OUT = (os.path.abspath(a) for a in argv[:4])
ONLY = set(opt["--only"].split(",")) if "--only" in opt else None
COVER, MARGIN, CAP = float(opt.get("--cover", 98)), float(opt.get("--margin", 0.001)), float(opt.get("--cap", 0.02))
REACH = 0.03
os.makedirs(OUT, exist_ok=True)
t0 = time.time()


def world(o):
    me = o.data
    m = np.array(o.matrix_world)
    co = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("co", co)
    no = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get("normal", no)
    N = no.reshape(-1, 3) @ m[:3, :3].T
    return co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3], N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)


def tris(o, P):
    o.data.calc_loop_triangles()
    t = np.empty(len(o.data.loop_triangles) * 3, np.int64)
    o.data.loop_triangles.foreach_get("vertices", t)
    return BVHTree.FromPolygons(P.tolist(), t.reshape(-1, 3).tolist(), all_triangles=True)


# --- body: outer skin sample ---------------------------------------------------------------------------
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=BASE)
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
roles = json.load(open(ROLES))
gn = {g.index: g.name for g in body.vertex_groups}
main = np.array([gn[max(v.groups, key=lambda g: g.weight).group] if len(v.groups) else "" for v in body.data.vertices])
BV, BN = world(body)
h = float(np.ptp(BV[:, 2]))
bvh_b = tris(body, BV)


def sees_out(p, n):
    n = Vector(n)
    t1 = n.cross(Vector((0, 0, 1)))
    t1 = (t1 if t1.length > 1e-3 else n.cross(Vector((1, 0, 0)))).normalized()
    t2 = n.cross(t1)
    o = Vector(p) + n * 1e-5 * h
    return any(bvh_b.ray_cast(o, d, 3 * h)[0] is None
               for d in (n, n * 0.5 + t1 * 0.87, n * 0.5 - t1 * 0.87, n * 0.5 + t2 * 0.87, n * 0.5 - t2 * 0.87))


rng = np.random.default_rng(0)
cand = np.nonzero(rng.random(len(BV)) < 0.25)[0]
skin = np.array([i for i in cand if sees_out(BV[i], BN[i])])
tree_skin = cKDTree(BV[skin])
print(f"body {len(BV)} verts, outer-skin sample {len(skin)}, h {h:.3f}", flush=True)

# --- parts ---------------------------------------------------------------------------------------------
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=PARTS)
parts = {o.name.split(".")[0]: o for o in bpy.data.objects if o not in before and o.type == "MESH"}
for o in [o for o in bpy.data.objects if o not in before and o.type != "MESH"]:
    bpy.data.objects.remove(o, do_unlink=True)
report = {"settings": {"cover_pct": COVER, "margin_h": MARGIN, "cap_h": CAP, "reach_h": REACH, "pose": "rest"}, "pieces": {}}
for name, o in sorted(parts.items()):
    if name == "head" or (ONLY is not None and name not in ONLY):
        continue
    P, N = world(o)
    bvh = tris(o, P)
    mine = skin[np.isin(main[skin], skin_bones(name, roles))]
    need = []
    for i in mine:
        p, n = Vector(BV[i]), Vector(BN[i])
        loc = bvh.find_nearest(p)[0]
        if loc is None or (loc - p).length > REACH * h:
            continue                                   # not under this piece
        o_, left, cov = p + n * 1e-5 * h, REACH * h, False
        while left > 0:
            hit, fn, _, d = bvh.ray_cast(o_, n, left)
            if hit is None:
                break
            if fn.dot(n) > 0:
                cov = True
                break
            o_, left = hit + n * 1e-6 * h, left - d
        need.append(0.0 if cov else (loc - p).length / h + MARGIN)
    need = np.array(need)
    b = float(min(np.percentile(need, COVER), CAP)) if len(need) else 0.0
    _, j = tree_skin.query(P, workers=-1)
    s = np.sign(((P - BV[skin[j]]) * N).sum(1))
    s[s == 0] = 1
    Pn = P + N * s[:, None] * b * h
    mw_inv = np.linalg.inv(np.array(o.matrix_world))
    o.data.vertices.foreach_set("co", (Pn @ mw_inv[:3, :3].T + mw_inv[:3, 3]).astype(np.float32).ravel())
    o.data.update()
    row = {"skin_under": int(len(need)), "covered_before_pct": float(100 * (need == 0).mean()) if len(need) else None,
           "buffer_h_pct": round(b * 100, 3), "capped": bool(len(need) and np.percentile(need, COVER) > CAP),
           "covered_after_pct": float(100 * (need <= b).mean()) if len(need) else None}
    report["pieces"][name] = row
    print(f"{name:11s} skin {row['skin_under']:6d}  covered {row['covered_before_pct'] or 0:5.1f} %  -> buffer "
          f"{row['buffer_h_pct']:.2f} % h{' (cap)' if row['capped'] else ''}  -> covered {row['covered_after_pct'] or 0:5.1f} %",
          flush=True)
for o in parts.values():
    for m in o.data.materials:
        if m is not None:
            m.use_backface_culling = False          # glTF doubleSided: thin plates keep their undersides
bpy.ops.object.select_all(action="DESELECT")
for o in parts.values():
    o.select_set(True)
bpy.context.view_layer.objects.active = next(iter(parts.values()))
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "parts_buffer.glb"), use_selection=True)
report["seconds"] = round(time.time() - t0)
json.dump(report, open(os.path.join(OUT, "buffer.json"), "w"), indent=1)
print(f"BUFFER_OK {report['seconds']} s")
