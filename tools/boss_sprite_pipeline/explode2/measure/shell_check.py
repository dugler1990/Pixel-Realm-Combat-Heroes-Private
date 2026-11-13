"""Is his skin inside the armour, and how far does the plate stand off it? At rest, whole outfit, before any cut.

    .venv-bpy/Scripts/python.exe shell_check.py <base_rigged.glb> <roles.json> <outfit_aligned.glb> [--json <file>]

<outfit_aligned.glb>: the outfit in the base's coordinates (explode2/outfit_skeleton.py output). For a sample of
the body's outer skin (a ray along the normal or tilted round it leaves the body; 1 vertex in 4, seeded), head and
neck left out: a ray goes out along the skin normal; the skin is INSIDE the armour when the ray leaves the outfit's
surface (hits an outward-facing outfit face) within 3 % h, else it is OUT (pokes through or is uncovered).
For inside skin, the stand-off is the distance to that outer surface (plate thickness + gap).
Prints the out share and stand-off (median, 10th percentile) per region, writes --json.
"""
import json
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
JSON = None
if "--json" in argv:
    i = argv.index("--json")
    JSON = argv[i + 1]
    del argv[i:i + 2]
BASE, ROLES, OUTFIT = argv[:3]
REACH = 0.03


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    return [o for o in bpy.data.objects if o.type == "MESH"]


def tris(objs):
    """World triangles of meshes as (verts, faces), triangulated."""
    V, F, off = [], [], 0
    for o in objs:
        me = o.data
        me.calc_loop_triangles()
        m = np.array(o.matrix_world)
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        V.append(co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3])
        t = np.empty(len(me.loop_triangles) * 3, np.int64)
        me.loop_triangles.foreach_get("vertices", t)
        F.append(t.reshape(-1, 3) + off)
        off += len(me.vertices)
    return np.concatenate(V), np.concatenate(F)


roles = json.load(open(ROLES))
body = max(load(BASE), key=lambda o: len(o.data.vertices))
gn = {g.index: g.name for g in body.vertex_groups}
main = np.array([gn[max(v.groups, key=lambda g: g.weight).group] if len(v.groups) else "" for v in body.data.vertices])
BV, BF = tris([body])
me = body.data
no = np.empty(len(me.vertices) * 3, np.float32)
me.vertices.foreach_get("normal", no)
BN = no.reshape(-1, 3) @ np.array(body.matrix_world)[:3, :3].T
BN /= np.maximum(np.linalg.norm(BN, axis=1, keepdims=True), 1e-12)
h = float(np.ptp(BV[:, 2]))
bvh_b = BVHTree.FromPolygons(BV.tolist(), BF.tolist(), all_triangles=True)

al, ar, ll, lr = roles["arm_l"], roles["arm_r"], roles["leg_l"], roles["leg_r"]
REGION = {}
for b in (roles["root"], roles["spine"], roles["spine2"], roles["chest"], al["shoulder"], ar["shoulder"]):
    REGION[b] = "torso"
for a in (al, ar):
    REGION[a["elbow"]] = "upper arm"
    REGION[a["wrist"]] = "forearm"
    REGION[a["hand"]] = "hand"
for l in (ll, lr):
    REGION[l["hip"]] = "thigh"
    REGION[l["knee"]] = "shin"
    REGION[l["ankle"]] = "foot"
    REGION[l["foot"]] = "foot"
for g in gn.values():                      # fingers: bones without a role under the hands
    REGION.setdefault(g, "hand" if g not in (roles["neck"], roles["head"]) else None)

rng = np.random.default_rng(0)
cand = np.nonzero(np.array([REGION.get(m) is not None for m in main]))[0]
cand = cand[rng.random(len(cand)) < 0.25]


def sees_out(p, n):
    n = Vector(n)
    t1 = n.cross(Vector((0, 0, 1)))
    t1 = (t1 if t1.length > 1e-3 else n.cross(Vector((1, 0, 0)))).normalized()
    t2 = n.cross(t1)
    o = Vector(p) + n * 1e-5 * h
    return any(bvh_b.ray_cast(o, d, 3 * h)[0] is None
               for d in (n, n * 0.5 + t1 * 0.87, n * 0.5 - t1 * 0.87, n * 0.5 + t2 * 0.87, n * 0.5 - t2 * 0.87))


skin = np.array([i for i in cand if sees_out(BV[i], BN[i])])
print(f"body {len(BV)} verts, sampled outer skin {len(skin)} (head / neck left out), h {h:.3f}")

OV, OF = tris(load(OUTFIT))
bvh_o = BVHTree.FromPolygons(OV.tolist(), OF.tolist(), all_triangles=True)
inside = np.zeros(len(skin), bool)
gap = np.full(len(skin), np.nan)
for k, i in enumerate(skin):
    n = Vector(BN[i])
    o = Vector(BV[i]) + n * 1e-5 * h
    left = REACH * h
    travelled = 0.0
    while left > 0:
        loc, fn, _, d = bvh_o.ray_cast(o, n, left)
        if loc is None:
            break
        travelled += d
        if fn.dot(n) > 0:                  # leaving the outfit's surface: the skin was under it
            inside[k] = True
            gap[k] = travelled / h * 100
            break
        o = loc + n * 1e-6 * h
        left -= d
depth = np.full(len(skin), np.nan)          # OUT skin: distance to the nearest outfit surface (% h) = how much
for k in np.nonzero(~inside)[0]:            # the outfit would have to grow there to cover it
    loc = bvh_o.find_nearest(Vector(BV[skin[k]]))[0]
    depth[k] = (loc - Vector(BV[skin[k]])).length / h * 100 if loc is not None else np.inf
reg = np.array([REGION[main[i]] for i in skin])
out = {"outfit": OUTFIT, "reach_h": REACH, "sampled": int(len(skin)), "regions": {}}
print(f"{'region':10s} {'skin':>6s} {'OUT %':>6s} {'stand-off median':>17s} {'p10':>6s}   OUT by: p50   p90  "
      f"(% h)   OUT % left if grown by 0.5 / 1 / 2 % h")
for r in ["torso", "upper arm", "forearm", "hand", "thigh", "shin", "foot", "ALL"]:
    m = np.ones(len(reg), bool) if r == "ALL" else reg == r
    if not m.any():
        continue
    g = gap[m & inside]
    d = depth[m & ~inside]
    row = {"n": int(m.sum()), "out_pct": float(100 * (~inside[m]).mean()),
           "standoff_median": float(np.median(g)) if len(g) else None,
           "standoff_p10": float(np.percentile(g, 10)) if len(g) else None,
           "out_by_p50": float(np.percentile(d, 50)) if len(d) else 0.0,
           "out_by_p90": float(np.percentile(d, 90)) if len(d) else 0.0,
           "out_left_if_grown": {str(b): float(100 * (d > b).sum() / m.sum()) for b in (0.5, 1.0, 2.0)}}
    out["regions"][r] = row
    left = row["out_left_if_grown"]
    print(f"{r:10s} {row['n']:6d} {row['out_pct']:6.1f} {row['standoff_median'] or 0:17.2f} {row['standoff_p10'] or 0:6.2f}"
          f"          {row['out_by_p50']:5.2f} {row['out_by_p90']:5.2f}           "
          f"{left['0.5']:5.1f} / {left['1.0']:5.1f} / {left['2.0']:5.1f}")
ny = BN[skin][:, 1]                         # figure faces -y: which way the skin faces
sides = {"front-facing": ny < -0.3, "side-facing": np.abs(ny) <= 0.3, "back-facing": ny > 0.3}
out["sides"] = {k: {"n": int(m.sum()), "out_pct": float(100 * (~inside[m]).mean())} for k, m in sides.items()}
print("  ".join(f"{k} {v['out_pct']:.1f} % OUT (n {v['n']})" for k, v in out["sides"].items()))
if JSON:
    json.dump(out, open(JSON, "w"), indent=1)
    print("wrote", JSON)
