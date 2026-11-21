"""Bind: the orientation each driven bone starts from, and the source reference it is measured against.

world_rotation(target, t) = Rsrc(t) . Rsrc(ref)^-1 . bind(target)

bind(target) is the target's rest rotation, turned (when bind is on for that role) by the minimal
rotation that aims the bone's +Y along the source bone's +Y at the reference pose. Bind off: the
bone keeps its rest orientation and plays the change from the reference on top.

Reference pose: "frame1" (the clip's first frame, graded good), "tpose" (the BVH header rest), or
idle rotations {joint: 3x3} from an idle_pose.json. No role is skipped in code: the per-role flags
come from the character file.
"""
from __future__ import annotations

import numpy as np

from .linalg import Y, ncols, rot_between, unit


def bind(use: list[tuple[str, str, str]], src_ref_world: dict, src_rest_world: dict,
         rest_rot: dict, flags: dict[str, bool], reference: str,
         idle_rots: dict | None = None, axis: str = "bone_y", segments=None,
         rest_world: dict | None = None) -> tuple[dict, dict]:
    """use: [(role, source joint, target bone)].
    src_ref_world: joint -> 4x4 world at the clip's first frame. src_rest_world: joint -> 4x4 at rest.
    axis "bone_y": aim the bone's +Y along the source bone's +Y (graded barb bake; folds the barb's hips,
    149.3 deg, because UniRig's hip bone axis is not the source's). axis "joint" (experiment 1,
    2026-11-21): aim the bone's segment to its driven child along the source's segment; a bone with
    no driven child keeps the +Y rule. barb_hit_heavy_01, all bound: hips 0.0, neck 0.2, worst 22.2 -
    but that is the quantity the pose check measures; twist is not measured.
    Returns (bind_rot: bone -> 3x3, ref_inv: joint -> 3x3)."""
    child = {t: (s2, t2) for _, _, t, s2, t2 in (segments or [])}
    ref_inv = {s: np.linalg.inv(ncols(src_ref_world[s][:3, :3])) for _, s, _ in use}
    ref_rots = dict(idle_rots or {})
    if reference == "tpose" and not ref_rots:
        ref_rots = {s: ncols(src_rest_world[s][:3, :3]) for _, s, _ in use}
    bind_rot = dict(rest_rot)
    for role, s, t in use:
        if not flags.get(role, False):
            continue
        if axis == "joint" and t in child and rest_world is not None:
            s2, t2 = child[t]
            ds = unit(src_ref_world[s2][:3, 3] - src_ref_world[s][:3, 3])
            dt = unit(rest_world[t2][:3, 3] - rest_world[t][:3, 3])
            bind_rot[t] = rot_between(dt, ds) @ rest_rot[t]
            continue
        ref = ref_rots.get(s)
        if ref is None:
            ref = src_ref_world[s][:3, :3]
        ds = unit(ncols(ref) @ Y)
        dt = unit(rest_rot[t] @ Y)
        bind_rot[t] = rot_between(dt, ds) @ rest_rot[t]
    for role, s, t in use:
        if s in ref_rots and flags.get(role, False):
            ref_inv[s] = np.linalg.inv(ncols(ref_rots[s]))
    return bind_rot, ref_inv
