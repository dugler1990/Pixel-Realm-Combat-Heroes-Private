"""New skin weights for a rigged GLB, same skeleton.

    .venv-bpy/Scripts/python.exe rig_reweight.py <rigged.glb> <out.glb> heat <voxel % of h> | smooth <iters>

See PROCESS_rigfix.md. heat 0.5 is the pick for the barb (2026-11-01).

smooth: diffuse the existing weights over the surface (position-welded graph, so UV seams do not
        stop it), then keep the 4 strongest bones per vertex and renormalise: ragged cut-offs fade.
heat:   voxel-remesh a watertight copy of the body, give it Blender's bone-heat automatic weights
        (they follow each bone's shape and reach, which TRELLIS's open/non-manifold mesh breaks),
        then transfer them onto the real mesh (nearest face, interpolated), limit 4, normalise.
"""
import os
import sys
import time

import bpy
import numpy as np

GLB, OUT, MODE, PARAM = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2]), sys.argv[3], float(sys.argv[4])
t0 = time.time()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
me = body.data
n = len(me.vertices)
names = [g.name for g in body.vertex_groups]


def read_weights(o):
    gn = [g.name for g in o.vertex_groups]
    W = np.zeros((len(o.data.vertices), len(names)), np.float32)
    for v in o.data.vertices:
        for g in v.groups:
            W[v.index, names.index(gn[g.group])] = g.weight
    return W


def write_weights(o, W):
    W = W.copy()
    top = np.argsort(-W, 1)[:, :4]
    keep = np.zeros_like(W, bool)
    np.put_along_axis(keep, top, True, 1)
    W[~keep] = 0
    W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
    for g in list(o.vertex_groups):
        o.vertex_groups.remove(g)
    for gi, name in enumerate(names):
        vg = o.vertex_groups.new(name=name)
        nz = np.nonzero(W[:, gi] > 1e-3)[0]
        q = np.round(W[nz, gi] * 1000).astype(int)
        for level in np.unique(q):
            vg.add(nz[q == level].tolist(), level / 1000.0, "REPLACE")


if MODE == "smooth":
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    V = co.reshape(-1, 3)
    h = float(np.ptp(V[:, 2]))
    _, wid = np.unique(np.round(V / (1e-6 * h)).astype(np.int64), axis=0, return_inverse=True)
    wid = wid.ravel()
    nW = wid.max() + 1
    rep = np.zeros(nW, np.int64)
    rep[wid] = np.arange(n)
    e = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", e)
    E = np.unique(np.sort(wid[e.reshape(-1, 2)], 1), axis=0)
    E = E[E[:, 0] != E[:, 1]]
    deg = np.bincount(E[:, 0], minlength=nW) + np.bincount(E[:, 1], minlength=nW)
    WW = read_weights(body)[rep]
    for _ in range(int(PARAM)):
        s = np.zeros_like(WW)
        for j in range(WW.shape[1]):
            s[:, j] = np.bincount(E[:, 0], weights=WW[E[:, 1], j], minlength=nW) + \
                      np.bincount(E[:, 1], weights=WW[E[:, 0], j], minlength=nW)
        WW = 0.5 * WW + 0.5 * s / np.maximum(deg, 1)[:, None]
    write_weights(body, WW[wid])
    print(f"smoothed {int(PARAM)} iterations", flush=True)
else:
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    h = float(np.ptp(co.reshape(-1, 3)[:, 2]))
    proxy = body.copy()
    proxy.data = body.data.copy()
    proxy.name = "proxy"
    bpy.context.scene.collection.objects.link(proxy)
    for m in list(proxy.modifiers):
        proxy.modifiers.remove(m)
    for g in list(proxy.vertex_groups):
        proxy.vertex_groups.remove(g)
    proxy.parent = None
    proxy.matrix_world = body.matrix_world.copy()
    rm = proxy.modifiers.new("remesh", "REMESH")
    rm.mode = "VOXEL"
    rm.voxel_size = PARAM / 100 * h
    bpy.context.view_layer.objects.active = proxy
    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True)
    bpy.ops.object.modifier_apply(modifier="remesh")
    print(f"proxy {len(proxy.data.vertices)} verts (voxel {PARAM}% of h) in {time.time() - t0:.0f} s", flush=True)
    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    got = [g.name for g in proxy.vertex_groups]
    print(f"bone heat: {len(got)} groups in {time.time() - t0:.0f} s", flush=True)
    assert got, "bone heat produced no weights"
    for g in list(body.vertex_groups):
        body.vertex_groups.remove(g)
    for name in names:
        body.vertex_groups.new(name=name)
    dt = body.modifiers.new("dt", "DATA_TRANSFER")
    dt.object = proxy
    dt.use_vert_data = True
    dt.data_types_verts = {"VGROUP_WEIGHTS"}
    dt.vert_mapping = "POLYINTERP_NEAREST"
    dt.layers_vgroup_select_src = "ALL"
    dt.layers_vgroup_select_dst = "NAME"
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    while body.modifiers[0].name != "dt":
        bpy.ops.object.modifier_move_up(modifier="dt")
    bpy.ops.object.modifier_apply(modifier="dt")
    write_weights(body, read_weights(body))
    bpy.data.objects.remove(proxy, do_unlink=True)
    print(f"transferred to {n} verts in {time.time() - t0:.0f} s", flush=True)

bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
arm.select_set(True)
bpy.ops.export_scene.gltf(filepath=OUT, use_selection=True)
print("REWEIGHT_OK", OUT, f"{time.time() - t0:.0f} s", flush=True)
