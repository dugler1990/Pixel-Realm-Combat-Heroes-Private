"""Export an animated rig to a runtime mesh pack the engine can draw directly (method B).

    .venv-bpy/Scripts/python.exe export_mesh_runtime.py <animated.blend> <out_dir> [tris] [tex_px]
        [--only name,name] [extra.blend ...]

NLA tracks alone are not enough: some approved clips (e.g. settle_01) live only on
bpy.data.actions. Extra blends are appended so one pack can ship idle from one file
and walk from another without a second decimate.

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
import os
import sys
import time

import bpy
import numpy as np


def log(*a):
    print("[mesh_runtime]", *a, flush=True)


def parse_args(argv):
    if len(argv) < 2:
        raise SystemExit(
            "usage: export_mesh_runtime.py <blend> <out_dir> [tris] [tex] [--only a,b] [--skin] [extra.blend ...]"
        )
    src = os.path.abspath(argv[0])
    out = os.path.abspath(argv[1])
    tris, tex = 20000, 1024
    only = None
    extras = []
    skin = False
    i = 2
    if i < len(argv) and argv[i].lstrip("-").isdigit():
        tris = int(argv[i])
        i += 1
    if i < len(argv) and argv[i].lstrip("-").isdigit():
        tex = int(argv[i])
        i += 1
    while i < len(argv):
        arg = argv[i]
        if arg == "--only":
            only = {n.strip() for n in argv[i + 1].split(",") if n.strip()}
            i += 2
        elif arg.startswith("--only="):
            only = {n.strip() for n in arg.split("=", 1)[1].split(",") if n.strip()}
            i += 1
        elif arg == "--skin":
            skin = True
            i += 1
        else:
            extras.append(os.path.abspath(arg))
            i += 1
    return src, out, tris, tex, only, extras, skin


def collect_actions(arm, only):
    """NLA tracks plus leftover bpy.data.actions (settle_01 is not on a track)."""
    actions = {}
    ad = arm.animation_data
    if ad:
        for t in ad.nla_tracks:
            if t.strips and t.strips[0].action:
                actions[t.name] = t.strips[0].action
    for action in bpy.data.actions:
        actions.setdefault(action.name, action)
    if only:
        missing = only - set(actions)
        if missing:
            log("missing requested actions", sorted(missing), "have", sorted(actions))
        actions = {name: action for name, action in actions.items() if name in only}
    if not actions:
        raise SystemExit("no actions to bake")
    return actions


def append_actions(blend_path, only):
    with bpy.data.libraries.load(blend_path, link=False) as (data_from, data_to):
        names = list(data_from.actions)
        if only:
            names = [name for name in names if name in only]
        data_to.actions = names
    log("appended from", os.path.basename(blend_path), [a.name for a in data_to.actions])


def _np_mat(m):
    return np.array(m, dtype=np.float64)


def _check_linear_skin(mesh):
    """Standard linear skinning matches to_mesh() only when these all hold."""
    problems = []
    if mesh.data.shape_keys is not None:
        problems.append("shape keys present")
    arm_mods = [m for m in mesh.modifiers if m.type == "ARMATURE"]
    if not arm_mods:
        problems.append("no armature modifier")
    else:
        last = arm_mods[-1]
        if getattr(last, "use_deform_preserve_volume", False):
            problems.append("preserve volume is on")
        if getattr(last, "use_bone_envelopes", False):
            problems.append("bone envelopes are on")
        idx = mesh.modifiers.find(last.name)
        after = [m.name for m in mesh.modifiers[idx + 1:] if m.type != "DECIMATE"]
        if after:
            problems.append("modifiers after armature: %s" % after)
    if problems:
        log("DEFORM CHECK FAILED", problems)
    else:
        log("deform check ok: preserve volume off, envelopes off, no shape keys, armature last")
    return problems


def _bind_weights(mesh, arm):
    """Top 4 use_deform influences. Zero-weight verts point at the identity slot."""
    deform = [b.name for b in arm.data.bones if b.use_deform]
    group_name = {g.index: g.name for g in mesh.vertex_groups}
    name_to_i = {name: i for i, name in enumerate(deform)}
    identity = len(deform)
    n = len(mesh.data.vertices)
    joints = np.zeros((n, 4), np.uint16)
    weights = np.zeros((n, 4), np.float32)
    fifth = 0
    zero = 0
    for vi, v in enumerate(mesh.data.vertices):
        pairs = []
        for g in v.groups:
            name = group_name.get(g.group)
            if name in name_to_i and g.weight > 0.0:
                pairs.append((g.weight, name_to_i[name]))
        pairs.sort(reverse=True)
        if len(pairs) >= 5 and pairs[4][0] > 0.05:
            fifth += 1
        pairs = pairs[:4]
        total = sum(w for w, _ in pairs)
        if total <= 1e-8:
            zero += 1
            joints[vi, 0] = identity
            weights[vi, 0] = 1.0
            continue
        for k, (w, ji) in enumerate(pairs):
            joints[vi, k] = ji
            weights[vi, k] = w / total
    log("weights", "deform_bones", len(deform), "identity_slot", identity,
        "fifth_above_0.05", fifth, "zero_deform", zero, "verts", n)
    return deform, joints, weights, identity


def _skin_points(rest, joints, weights, mats):
    """rest [V,3] already in pivot space. mats [B,4,4] row-major."""
    hom = np.c_[rest, np.ones(len(rest), np.float32)]
    out = np.zeros((len(rest), 3), np.float32)
    for k in range(4):
        mk = mats[joints[:, k]]
        posed = np.einsum("vij,vj->vi", mk, hom, optimize=True)[:, :3]
        out += weights[:, k:k+1] * posed
    return out


def bake_skin(arm, mesh, scene, actions, out, fps, t0):
    """Write skin.npz beside mesh.npz. Does not replace the baked pack."""
    problems = _check_linear_skin(mesh)
    names, joints, weights, identity = _bind_weights(mesh, arm)
    bone_count = identity + 1

    mw0 = _np_mat(mesh.matrix_world)
    rest_co = np.empty(len(mesh.data.vertices) * 3, np.float32)
    mesh.data.vertices.foreach_get("co", rest_co)
    rest_co = rest_co.reshape(-1, 3)
    rest_h = np.c_[rest_co, np.ones(len(rest_co))]
    rest_pos = (rest_h @ mw0.T)[:, :3].astype(np.float32)
    nrm = np.empty(len(rest_co) * 3, np.float32)
    mesh.data.vertices.foreach_get("normal", nrm)
    nrm = nrm.reshape(-1, 3) @ mw0[:3, :3].T
    nrm /= (np.linalg.norm(nrm, axis=1, keepdims=True) + 1e-9)
    rest_nrm = np.clip(nrm * 127, -127, 127).astype(np.int8)

    mesh.data.calc_loop_triangles()
    tri = np.empty(len(mesh.data.loop_triangles) * 3, np.int32)
    mesh.data.loop_triangles.foreach_get("vertices", tri)
    idx_arr = tri.reshape(-1, 3).astype(np.uint32)
    uv_layer = mesh.data.uv_layers.active.data
    uv_arr = np.zeros((len(rest_co), 2), np.float32)
    seen = np.zeros(len(rest_co), bool)
    for poly in mesh.data.polygons:
        for li, vi in zip(poly.loop_indices, poly.vertices):
            if not seen[vi]:
                uv_arr[vi] = uv_layer[li].uv
                seen[vi] = True
    uv_arr = uv_arr.astype(np.float16)

    ad = arm.animation_data
    ranges = {}
    skin = []
    max_err = 0.0
    posed_lo = np.array([np.inf, np.inf, np.inf])
    posed_hi = np.array([-np.inf, -np.inf, -np.inf])
    mw_changed = False
    eye = np.eye(4, dtype=np.float32)
    frame_i = 0
    # Corrective smooth (and anything else after the armature) is not linear skinning.
    # Mute it for the position check so a large error means the matrix, not the deform model.
    post_mods = []
    arm_mods = [m for m in mesh.modifiers if m.type == "ARMATURE"]
    if arm_mods:
        idx = mesh.modifiers.find(arm_mods[-1].name)
        post_mods = [m for m in mesh.modifiers[idx + 1:] if m.type != "DECIMATE"]
    saved_post = [(m, m.show_viewport, m.show_render) for m in post_mods]
    for m, _, _ in saved_post:
        m.show_viewport = False
        m.show_render = False
    cs_delta = None
    for name in sorted(actions):
        action = actions[name]
        ad.action = action
        if hasattr(action, "slots") and hasattr(ad, "action_slot") and len(action.slots):
            ad.action_slot = action.slots[0]
        f0, f1 = int(action.frame_start), int(action.frame_end)
        start = frame_i
        for f in range(f0, f1 + 1):
            scene.frame_set(f)
            bpy.context.view_layer.update()
            mw = _np_mat(mesh.matrix_world)
            if not np.allclose(mw, mw0, atol=1e-5):
                mw_changed = True
            arm_w = arm.matrix_world
            arm_inv = arm_w.inverted()
            mats = np.empty((bone_count, 4, 4), np.float32)
            by_name = {pb.name: pb for pb in arm.pose.bones}
            for i, bname in enumerate(names):
                pb = by_name[bname]
                M = arm_w @ pb.matrix @ pb.bone.matrix_local.inverted() @ arm_inv
                mats[i] = np.array(M, dtype=np.float32)
            mats[identity] = eye
            skin.append(mats)
            posed = _skin_points(rest_pos, joints, weights, mats)
            posed_lo = np.minimum(posed_lo, posed.min(0))
            posed_hi = np.maximum(posed_hi, posed.max(0))
            dg = bpy.context.evaluated_depsgraph_get()
            ev = mesh.evaluated_get(dg)
            me = ev.to_mesh()
            co = np.empty(len(me.vertices) * 3, np.float32)
            me.vertices.foreach_get("co", co)
            baked = (np.c_[co.reshape(-1, 3), np.ones(len(me.vertices))] @ mw.T)[:, :3]
            ev.to_mesh_clear()
            if baked.shape == posed.shape:
                max_err = max(max_err, float(np.max(np.abs(posed - baked))))
            if frame_i == start and post_mods and baked.shape == posed.shape:
                for m, vp, rd in saved_post:
                    m.show_viewport, m.show_render = vp, rd
                dg = bpy.context.evaluated_depsgraph_get()
                ev = mesh.evaluated_get(dg)
                me = ev.to_mesh()
                co = np.empty(len(me.vertices) * 3, np.float32)
                me.vertices.foreach_get("co", co)
                with_post = (np.c_[co.reshape(-1, 3), np.ones(len(me.vertices))] @ mw.T)[:, :3]
                ev.to_mesh_clear()
                for m, _, _ in saved_post:
                    m.show_viewport = False
                    m.show_render = False
                if with_post.shape == posed.shape:
                    delta = np.abs(with_post - baked)
                    this = float(delta.max())
                    over = int(np.any(delta > 0.0026, axis=1).sum())
                    cs_delta = this if cs_delta is None else max(cs_delta, this)
                    log("post_armature_delta", name, round(this, 6), "verts_over_2px", over)
            frame_i += 1
            if frame_i == 8 and max_err > 0.02:
                log("ABORT skin error on first frames", round(max_err, 6))
                raise SystemExit(2)
        ranges[name] = [start, frame_i - 1]
        ad.action = None
        log("skinned", name, ranges[name], "max_err", round(max_err, 6), "%.0fs" % (time.time() - t0))

    if mw_changed:
        log("mesh.matrix_world CHANGES across frames; identity slot is not valid for this export")
    skin_mats = np.stack(skin).astype(np.float32)
    pivot = [float((posed_lo[0] + posed_hi[0]) / 2), float((posed_lo[1] + posed_hi[1]) / 2), float(posed_lo[2])]
    np.savez_compressed(
        os.path.join(out, "skin.npz"),
        rest_pos=rest_pos.astype(np.float16),
        rest_nrm=rest_nrm,
        uv=uv_arr,
        indices=idx_arr,
        joints=joints,
        weights=weights.astype(np.float16),
        skin_mats=skin_mats,
        bone_names=np.array(names + ["__identity__"]),
        ranges=json.dumps(ranges),
        fps=fps,
        bbox_lo=posed_lo.astype(np.float32),
        bbox_hi=posed_hi.astype(np.float32),
        pivot=np.array(pivot, np.float32),
    )
    size_mb = os.path.getsize(os.path.join(out, "skin.npz")) / 1e6
    # Leave mesh.npz bytes alone. pack.json gains bones so the loader selects skin.npz.
    pack_path = os.path.join(out, "pack.json")
    pack = {}
    if os.path.isfile(pack_path):
        with open(pack_path, encoding="utf-8") as fh:
            pack = json.load(fh)
    pack.update({
        "format": "skin",
        "bones": bone_count,
        "frames": int(skin_mats.shape[0]),
        "verts": int(rest_pos.shape[0]),
        "tris": int(idx_arr.shape[0]),
        "ranges": ranges,
        "fps": fps,
        "pivot": pivot,
        "bbox": [posed_lo.tolist(), posed_hi.tolist()],
        "albedo": pack.get("albedo", "albedo.png"),
        "skin_npz_mb": round(size_mb, 1),
        "height_units": float(posed_hi[2] - posed_lo[2]),
        "max_skin_err": max_err,
        "mesh_matrix_changed": mw_changed,
        "deform_problems": problems,
        "post_armature_delta": cs_delta,
    })
    with open(pack_path, "w", encoding="utf-8") as fh:
        json.dump(pack, fh, indent=1)
    log("wrote skin.npz %.1f MB | %d frames x %d bones | max_err %.5f | %.0fs" % (
        size_mb, skin_mats.shape[0], bone_count, max_err, time.time() - t0))


SRC, OUT, TRIS, TEX, ONLY, EXTRAS, SKIN = parse_args(sys.argv[1:])
os.makedirs(OUT, exist_ok=True)
t0 = time.time()

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
for extra in EXTRAS:
    append_actions(extra, ONLY)

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

# --- 3. bake every frame of every selected action ----------------------------------------------
if arm.animation_data is None:
    arm.animation_data_create()
ad = arm.animation_data
actions = collect_actions(arm, ONLY)
for t in ad.nla_tracks:
    t.mute = True
log("baking", {name: (int(a.frame_start), int(a.frame_end)) for name, a in actions.items()})
if SKIN:
    bake_skin(arm, mesh, scene, actions, OUT, fps, t0)
    raise SystemExit(0)

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
