"""Skin-weight numbers for a rigged glb. Runs in Blender (via rigging/blender/runner.py), fresh process.

Same measure as rigfix/rig_check.py: weights normalised per vertex; positions welded at 1e-6 of height
so UV-seam copies count once; neighbour jump = L1 distance of the weight vectors across a welded edge
(0..2). UniRig's barb: 1.95 % of edges jump > 0.3 (PROCESS_rigfix.md) - those cut-offs are the crinkles.
"""
from __future__ import annotations

import numpy as np


def measure(glb: str) -> dict:
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    body = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    me = body.data
    n = len(me.vertices)
    co = np.empty(n * 3, np.float32)
    me.vertices.foreach_get("co", co)
    mw = np.array(body.matrix_world)
    V = co.reshape(-1, 3) @ mw[:3, :3].T + mw[:3, 3]
    h = float(np.ptp(V[:, 2])) or 1.0
    names = [g.name for g in body.vertex_groups]
    W = np.zeros((n, max(1, len(names))), np.float32)
    for v in me.vertices:
        for g in v.groups:
            W[v.index, g.group] = g.weight
    raw_sum = W.sum(1)
    neutral = names.index("neutral_bone") if "neutral_bone" in names else None
    Wn = W / np.maximum(raw_sum[:, None], 1e-9)
    nz = (Wn > 1e-3).sum(1)
    _, wid = np.unique(np.round(V / (1e-6 * h)).astype(np.int64), axis=0, return_inverse=True)
    wid = wid.ravel()
    rep = np.zeros(wid.max() + 1, np.int64)
    rep[wid] = np.arange(n)
    e = np.empty(len(me.edges) * 2, np.int64)
    me.edges.foreach_get("vertices", e)
    E = np.unique(np.sort(wid[e.reshape(-1, 2)], 1), axis=0)
    E = E[E[:, 0] != E[:, 1]]
    WW = Wn[rep]
    jump = np.abs(WW[E[:, 0]] - WW[E[:, 1]]).sum(1) if len(E) else np.zeros(1)
    return {
        "verts": int(n),
        "groups": len(names),
        "influences_mean": round(float(nz.mean()), 3),
        "influences_max": int(nz.max()) if n else 0,
        "unweighted_verts": int((raw_sum <= 1e-6).sum()),
        "neutral_bone_verts": 0 if neutral is None else int((W[:, neutral] > 1e-6).sum()),
        "jump_median": round(float(np.median(jump)), 4),
        "jump_p99": round(float(np.percentile(jump, 99)), 4),
        "edges_jump_over_0_3_pct": round(float(100 * (jump > 0.3).mean()), 3),
    }
