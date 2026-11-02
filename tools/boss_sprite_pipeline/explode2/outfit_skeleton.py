"""Step 0: give an outfit mesh (TRELLIS, no rig) the base character's skeleton.

    .venv-bpy/Scripts/python.exe outfit_skeleton.py <base_rigged.glb> <outfit.glb> <out.glb>

1. align  one similarity onto the base body (same as explode_pose.load_parts): scale from height,
          bounding-box foot anchor, then the outfit's head ICP-matched onto the base head (the head is
          bare in both, so it is the reliable common part)
2. weights bone heat (as rig_reweight.py heat 0.5) on a solid proxy = voxel remesh (0.5 % of h) of the
          outfit joined with the base body, largest island only. The outfit alone is a hollow shell
          with the bones in the empty inside: bone heat finds no solution for any bone (all weights 0).
          The body fills the hollow; the remesh unions them; pockets between body and armour become
          separate closed islands, dropped. Weights go to the outfit by Data Transfer (nearest face,
          interpolated), top 4, normalised.
3. export the outfit parented to the base armature (the base's rest pose, unchanged), its own material
"""
import json
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "explode"))
from explode_common import world_verts

BASE, OUTFIT, OUT = (os.path.abspath(a) for a in sys.argv[1:4])
HEAD_FRAC = 0.12
VOXEL = 0.5          # % of height, as rig_reweight heat 0.5
t0 = time.time()

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=BASE)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
B = world_verts(body)
hB = float(np.ptp(B[:, 2]))
gnames = [g.name for g in body.vertex_groups]
W = np.zeros((len(B), len(gnames)), np.float32)
for v in body.data.vertices:
    for g in v.groups:
        W[v.index, g.group] = g.weight

before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=OUTFIT)
new = [o for o in bpy.data.objects if o not in before]
outfit = max((o for o in new if o.type == "MESH"), key=lambda o: len(o.data.vertices))
outfit.data.transform(outfit.matrix_world)
outfit.parent = None
outfit.matrix_world = Matrix.Identity(4)
for o in new:
    if o is not outfit:
        bpy.data.objects.remove(o, do_unlink=True)
outfit.name = "outfit"


def box_anchor(P):
    return np.array([(P[:, 0].min() + P[:, 0].max()) / 2, (P[:, 1].min() + P[:, 1].max()) / 2, P[:, 2].min()])


A = world_verts(outfit).astype(np.float64)
s = hB / float(np.ptp(A[:, 2]))
A = (A - box_anchor(A)) * s + box_anchor(B)
head_b = B[B[:, 2] > B[:, 2].max() - HEAD_FRAC * hB]
tree_head = cKDTree(head_b)
rng = np.random.default_rng(0)
for _ in range(40):
    hpts = A[A[:, 2] > A[:, 2].max() - HEAD_FRAC * hB]
    hpts = hpts[rng.choice(len(hpts), min(6000, len(hpts)), replace=False)]
    dist, idx = tree_head.query(hpts)
    keep = dist < np.percentile(dist, 90)
    delta = (head_b[idx[keep]] - hpts[keep]).mean(0)
    A += delta
    if np.linalg.norm(delta) < 1e-5 * hB:
        break
DIAG = {"step": "0 skeleton", "base": BASE, "outfit": OUTFIT, "out": OUT,
        "settings": {"head_frac": HEAD_FRAC, "voxel_pct_h": VOXEL, "weights": "bone heat on outfit+body voxel proxy, nearest-face transfer, top 4"},
        "results": {"scale": round(s, 5), "head_residual_pct_h": round(float(np.median(dist) / hB * 100), 3)}}
print(f"aligned: scale {s:.4f}, head residual median {np.median(dist) / hB * 100:.2f}% of height", flush=True)
outfit.data.vertices.foreach_set("co", A.astype(np.float32).ravel())
outfit.data.update()



def detached_copy(o, name):
    c = o.copy()
    c.data = o.data.copy()
    c.name = name
    bpy.context.scene.collection.objects.link(c)
    for m in list(c.modifiers):
        c.modifiers.remove(m)
    for g in list(c.vertex_groups):
        c.vertex_groups.remove(g)
    c.data.transform(o.matrix_world)
    c.parent = None
    c.matrix_world = Matrix.Identity(4)
    return c


proxy = detached_copy(outfit, "proxy")
fill = detached_copy(body, "fill")
bpy.ops.object.select_all(action="DESELECT")
proxy.select_set(True)
fill.select_set(True)
bpy.context.view_layer.objects.active = proxy
bpy.ops.object.join()
rm = proxy.modifiers.new("remesh", "REMESH")
rm.mode = "VOXEL"
rm.voxel_size = VOXEL / 100 * hB
bpy.ops.object.modifier_apply(modifier="remesh")
pm = proxy.data
e = np.empty(len(pm.edges) * 2, np.int64)
pm.edges.foreach_get("vertices", e)
e = e.reshape(-1, 2)
nv = len(pm.vertices)
ncomp, comp = connected_components(coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(nv, nv)), directed=False)
big = np.argmax(np.bincount(comp))
drop = np.nonzero(comp != big)[0]
print(f"proxy {nv} verts, {ncomp} islands; keeping the largest ({int((comp == big).sum())} verts)", flush=True)
DIAG["results"].update({"proxy_verts": nv, "proxy_islands": int(ncomp), "proxy_kept_verts": int((comp == big).sum())})
if len(drop):
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(pm)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in drop], context="VERTS")
    bm.to_mesh(pm)
    bm.free()
bpy.ops.object.select_all(action="DESELECT")
proxy.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type="ARMATURE_AUTO")
PW = np.zeros((len(pm.vertices), len(gnames)), np.float32)
pg = [g.name for g in proxy.vertex_groups]
for v in pm.vertices:
    for g in v.groups:
        PW[v.index, gnames.index(pg[g.group])] = g.weight
unw = int((PW.sum(1) < 1e-6).sum())
print(f"bone heat on proxy: {unw} of {len(PW)} proxy verts unweighted, {time.time() - t0:.0f} s", flush=True)
DIAG["results"]["proxy_unweighted"] = unw
assert unw < 0.01 * len(PW), "bone heat failed on the proxy"

for name in gnames:
    outfit.vertex_groups.new(name=name)
outfit.parent = arm
outfit.matrix_parent_inverse = arm.matrix_world.inverted()
dt = outfit.modifiers.new("dt", "DATA_TRANSFER")
dt.object = proxy
dt.use_vert_data = True
dt.data_types_verts = {"VGROUP_WEIGHTS"}
dt.vert_mapping = "POLYINTERP_NEAREST"
dt.layers_vgroup_select_src = "ALL"
dt.layers_vgroup_select_dst = "NAME"
bpy.ops.object.select_all(action="DESELECT")
outfit.select_set(True)
bpy.context.view_layer.objects.active = outfit
bpy.ops.object.modifier_apply(modifier="dt")
Wo = np.zeros((len(outfit.data.vertices), len(gnames)), np.float32)
og = [g.name for g in outfit.vertex_groups]
for v in outfit.data.vertices:
    for g in v.groups:
        Wo[v.index, gnames.index(og[g.group])] = g.weight
top = np.argsort(-Wo, 1)[:, :4]
keep = np.zeros_like(Wo, bool)
np.put_along_axis(keep, top, True, 1)
Wo[~keep] = 0
Wo /= np.maximum(Wo.sum(1, keepdims=True), 1e-9)
zero = int((Wo.sum(1) < 1e-6).sum())
print(f"outfit: {zero} of {len(Wo)} verts unweighted", flush=True)
DIAG["results"].update({"outfit_verts": len(Wo), "outfit_unweighted": zero})
assert zero == 0, "outfit vertices without weights"
for g in list(outfit.vertex_groups):
    outfit.vertex_groups.remove(g)
for gi, name in enumerate(gnames):
    vg = outfit.vertex_groups.new(name=name)
    nz = np.nonzero(Wo[:, gi] > 1e-3)[0]
    q = np.round(Wo[nz, gi] * 1000).astype(int)
    for level in np.unique(q):
        vg.add(nz[q == level].tolist(), level / 1000.0, "REPLACE")
outfit.modifiers.new("Armature", "ARMATURE").object = arm
bpy.data.objects.remove(proxy, do_unlink=True)
bpy.data.objects.remove(body, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
outfit.select_set(True)
arm.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, use_selection=True)
DIAG["results"]["seconds"] = round(time.time() - t0)
json.dump(DIAG, open(os.path.join(os.path.dirname(OUT), "diag_step0_skeleton.json"), "w"), indent=1)
print("SKELETON_OK", OUT, f"{time.time() - t0:.0f} s", flush=True)
