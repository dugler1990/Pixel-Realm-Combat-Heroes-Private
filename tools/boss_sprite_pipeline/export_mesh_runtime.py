"""Export an animated rig to a runtime mesh pack the engine can draw directly (method B).

    .venv-bpy/Scripts/python.exe export_mesh_runtime.py <animated.blend> <out_dir> [tris] [tex_px]

Method A (the D2 route) bakes every pose x direction to PNGs: ~1 GB and ~70 min per boss, and
the frame is as large as the widest pose. Method B ships geometry instead — one decimated mesh,
one texture, and the *vertex positions per animation frame* — and the GPU poses it at draw time.
Cost becomes (frames x verts x 12 bytes) + one texture, independent of screen size, and the boss
can be drawn at any scale with no re-render.

Output <out_dir>/:
    mesh.npz     positions [frames, V, 3] float16 (baked, no skinning needed at runtime),
                 normals [frames, V, 3] int8, uv [V, 2] float16, indices [T, 3] uint32,
                 per-action frame ranges, fps, bbox, pivot
    albedo.png   the material's base-colour texture
    pack.json    human-readable manifest of the above

Baking positions (rather than shipping bones + weights) keeps the runtime a plain
"upload a vertex buffer, draw triangles" — no skinning shader, no CPU matrix work.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Vector

SRC = os.path.abspath(sys.argv[1])
OUT = os.path.abspath(sys.argv[2])
TRIS = int(sys.argv[3]) if len(sys.argv) > 3 else 20000
TEX = int(sys.argv[4]) if len(sys.argv) > 4 else 1024
os.makedirs(OUT, exist_ok=True)
t0 = time.time()


def log(*a):
    print("[mesh_runtime]", *a, flush=True)


bpy.ops.wm.open_mainfile(filepath=SRC)
for coll in [c for c in bpy.data.collections if c.name.startswith("glTF_not_exported")]:
    for o in list(coll.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.data.collections.remove(coll)
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh = [o for o in bpy.data.objects if o.type == "MESH"][0]
scene = bpy.context.scene
fps = scene.render.fps
log("source", os.path.basename(SRC), "verts", len(mesh.data.vertices), "fps", fps)

# --- 1. texture: bake nothing, just save the material's image at TEX ---------------------------
img = mesh.material_slots[0].material.node_tree.nodes["Image Texture"].image
w, h = img.size
px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, -1)[:, :, :3]
from PIL import Image  # noqa: E402  (bpy's numpy path first)
tex = Image.fromarray((np.clip(np.flipud(px), 0, 1) * 255).astype(np.uint8))
if max(tex.size) > TEX:
    tex = tex.resize((TEX, TEX), Image.LANCZOS)
tex.save(os.path.join(OUT, "albedo.png"))
log("albedo", tex.size)

# --- 2. decimate ONCE, before any posing --------------------------------------------------------
# A Decimate modifier evaluated per frame collapses different edges in different poses, so the
# vertex count drifts and the frames cannot be stacked. Apply it to the rest mesh instead: one
# fixed topology, and the armature then deforms that.
bpy.ops.object.select_all(action="DESELECT")
mesh.select_set(True)
bpy.context.view_layer.objects.active = mesh
mesh.data.calc_loop_triangles()
n_tris = len(mesh.data.loop_triangles) or len(mesh.data.polygons) * 2
arm_mods = [m for m in mesh.modifiers if m.type == "ARMATURE"]
for m in arm_mods:
    m.show_viewport = False                      # decimate the REST shape, not a posed one
mod = mesh.modifiers.new("runtime_dec", "DECIMATE")
mod.decimate_type = "COLLAPSE"
mod.ratio = min(1.0, TRIS / max(n_tris, 1))
mod.use_collapse_triangulate = True
bpy.ops.object.modifier_apply(modifier=mod.name)
for m in arm_mods:
    m.show_viewport = True
mesh.data.calc_loop_triangles()
log("decimated %d -> %d tris, %d verts (topology now fixed)" %
    (n_tris, len(mesh.data.loop_triangles), len(mesh.data.vertices)))

# --- 3. bake every frame of every action -------------------------------------------------------
ad = arm.animation_data
actions = {t.name: t.strips[0].action for t in ad.nla_tracks if t.strips}
if not actions:
    actions = {a.name: a for a in bpy.data.actions}
for t in ad.nla_tracks:
    t.mute = True

dg = bpy.context.evaluated_depsgraph_get()
ranges, positions, normals = {}, [], []
uv_arr = idx_arr = None
for name in sorted(actions):
    action = actions[name]
    ad.action = action
    if hasattr(action, "slots") and hasattr(ad, "action_slot") and len(action.slots):
        ad.action_slot = action.slots[0]
    f0, f1 = int(action.frame_start), int(action.frame_end)
    start = len(positions)
    for f in range(f0, f1 + 1):
        scene.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = mesh.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        mw = np.array(mesh.matrix_world)
        n = len(me.vertices)
        co = np.empty(n * 3, np.float32); me.vertices.foreach_get("co", co)
        V = (np.c_[co.reshape(-1, 3), np.ones(n)] @ mw.T)[:, :3]
        nrm = np.empty(n * 3, np.float32); me.vertices.foreach_get("normal", nrm)
        N = (nrm.reshape(-1, 3) @ mw[:3, :3].T)
        N /= (np.linalg.norm(N, axis=1, keepdims=True) + 1e-9)
        positions.append(V.astype(np.float16))
        normals.append(np.clip(N * 127, -127, 127).astype(np.int8))
        if uv_arr is None:                                    # topology is identical every frame
            tri = np.empty(len(me.loop_triangles) * 3, np.int32)
            me.loop_triangles.foreach_get("vertices", tri)
            idx_arr = tri.reshape(-1, 3).astype(np.uint32)
            uv_layer = me.uv_layers.active.data
            uv_arr = np.zeros((n, 2), np.float32)
            seen = np.zeros(n, bool)
            for poly in me.polygons:
                for li, vi in zip(poly.loop_indices, poly.vertices):
                    if not seen[vi]:
                        uv_arr[vi] = uv_layer[li].uv
                        seen[vi] = True
            uv_arr = uv_arr.astype(np.float16)
            log("runtime mesh", n, "verts", len(idx_arr), "tris")
        ev.to_mesh_clear()
    ranges[name] = [start, len(positions) - 1]
    ad.action = None
    log("baked", name, ranges[name], "%.0fs" % (time.time() - t0))

P = np.stack(positions); N = np.stack(normals)
lo, hi = P.astype(np.float32).reshape(-1, 3).min(0), P.astype(np.float32).reshape(-1, 3).max(0)
pivot = [float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2), float(lo[2])]
np.savez_compressed(os.path.join(OUT, "mesh.npz"), positions=P, normals=N, uv=uv_arr,
                    indices=idx_arr, ranges=json.dumps(ranges), fps=fps,
                    bbox_lo=lo, bbox_hi=hi, pivot=np.array(pivot, np.float32))
size_mb = os.path.getsize(os.path.join(OUT, "mesh.npz")) / 1e6
json.dump({"frames": int(P.shape[0]), "verts": int(P.shape[1]), "tris": int(idx_arr.shape[0]),
           "ranges": ranges, "fps": fps, "pivot": pivot,
           "bbox": [lo.tolist(), hi.tolist()], "albedo": "albedo.png",
           "npz_mb": round(size_mb, 1), "height_units": float(hi[2] - lo[2])},
          open(os.path.join(OUT, "pack.json"), "w"), indent=1)
log("wrote mesh.npz %.1f MB | %d frames x %d verts | %.0fs" % (size_mb, P.shape[0], P.shape[1], time.time() - t0))
