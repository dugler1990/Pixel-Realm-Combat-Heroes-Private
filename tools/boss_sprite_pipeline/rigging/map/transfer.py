"""Transfer: a clip's source matrices -> per-frame pose of the target. Pure numpy, no Blender.

Port of the loop that lived in retarget_bvh.py main() (2026-11-21), same maths:

  world_rotation(target, t) = Rsrc(t) . Rsrc(ref)^-1 . bind(target)

parent-first; clavicles slerped toward the source by clavicle_damp; upper arms capped at arm_cap
(their children ride the correction); in ik mode the arm and leg chains are re-aimed by closed-form
two-bone IK to a target blended between limb-anchored and hip-anchored by ik_body; the root follows
the clip's travel scaled by target height / source height (root_loc).

Inputs (built by blender/pose_io.py, or by a test fixture):
  src = {"frames": [f0..f1], "world": {frame: {joint: 4x4}}, "rest_world": {joint: 4x4},
         "parent": {joint: parent}, "height_f0": float}
  rig = {"tw": 4x4, "rest_arm": {bone: 4x4}, "parent": {bone: parent}, "length": {bone: float},
         "height": float, "order": [bones parent-first]}
  roles: the rig version's {role: bone}
  use: [(role, source joint, target bone)] parent-first
  s: resolved setting values (mode, ik_body, root_loc, reference_pose, arm_cap, clavicle_damp,
     jaw_closed) + "flags" {role: bind on/off}

Output: {"frames", "rot": {bone: [[w,x,y,z]...]}, "loc": {root: [[x,y,z]...]}, "pose_check",
         "proportions", "info"} - pose basis values, written straight onto the pose bones.
"""
from __future__ import annotations

import math

import numpy as np

from .. import roles as R
from . import pose_check as PC
from . import proportions
from .bind import bind
from .linalg import (Y, Z, aim_dir, axis_angle, mat_to_quat, ncols, quat_axis_angle, quat_to_mat,
                     slerp_from_identity, translate, unit)

REQUIRED = ("mode", "ik_body", "root_loc", "reference_pose", "arm_cap", "clavicle_damp",
            "jaw_closed", "bind_axis", "flags")


def cap_elevation(m3, max_deg):
    """Stop a bone pointing higher than max_deg above horizontal; return the correction too."""
    d = unit(m3 @ Y)
    elev = math.degrees(math.asin(max(-1.0, min(1.0, d[2]))))
    if elev <= max_deg:
        return m3, None
    horiz = np.array([d[0], d[1], 0.0])
    if np.linalg.norm(horiz) < 1e-6:
        horiz = np.array([1.0, 0.0, 0.0])
    axis = np.cross(unit(horiz), Z)
    if np.linalg.norm(axis) < 1e-6:
        return m3, None
    r = axis_angle(unit(axis), -math.radians(elev - max_deg))
    return r @ m3, r


def two_bone_ik(a, target, pole, l1, l2):
    """Closed-form two-link IK; returns the middle joint."""
    to = target - a
    d = float(np.linalg.norm(to))
    if d < 1e-6:
        return a + np.array([0.0, 0.0, -l1])
    d = max(abs(l1 - l2) + 1e-4, min(l1 + l2 - 1e-4, d))
    n = unit(to)
    u = pole - a
    u = u - n * float(np.dot(u, n))
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(n, Z)
        if np.linalg.norm(u) < 1e-6:
            u = np.cross(n, [1.0, 0.0, 0.0])
    u = unit(u)
    cos_a = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2.0 * l1 * d)))
    ang = math.acos(cos_a)
    return a + l1 * (math.cos(ang) * n + math.sin(ang) * u)


def transfer(src: dict, rig: dict, roles: dict, use: list, s: dict, idle_rots: dict | None = None) -> dict:
    missing = [k for k in REQUIRED if k not in s]
    if missing:
        raise ValueError(f"transfer: settings missing {missing}")
    if s["mode"] not in ("ik", "rot"):
        raise ValueError(f"mode {s['mode']!r}")
    frames = list(src["frames"])
    f0, f1 = frames[0], frames[-1]
    W = src["world"]
    tw = np.asarray(rig["tw"], float)
    scale_x = float(np.linalg.norm(tw[:3, 0]))
    tw_inv = np.linalg.inv(tw)
    rest_world = {b: tw @ np.asarray(m, float) for b, m in rig["rest_arm"].items()}
    parent = rig["parent"]
    rest_rel = {b: (np.linalg.inv(rest_world[parent[b]]) @ rest_world[b]) if parent.get(b) else None
                for b in rest_world}
    rest_rot = {t: ncols(rest_world[t][:3, :3]) for _, _, t in use}
    rest_head = {t: rest_world[t][:3, 3].copy() for _, _, t in use}
    info = []

    segs = PC.segments(use, src["parent"], parent)
    bind_rot, ref_inv = bind(use, W[f0], src.get("rest_world", {}), rest_rot, s["flags"],
                             s["reference_pose"] if s["reference_pose"] in ("frame1", "tpose") else "idle",
                             idle_rots, axis=s["bind_axis"], segments=segs, rest_world=rest_world)

    t_of = {r: t for r, _, t in use}
    s_of = {r: sj for r, sj, _ in use}
    root_t = roles.get("root")
    root_src = s_of.get("root")
    clavicles = {roles[c] for c in R.CLAVICLES if c in roles}
    capped = {}
    for side in R.SIDES:
        up, lo, end = (roles.get(f"upper_arm{side}"), roles.get(f"forearm{side}"), roles.get(f"hand{side}"))
        if up:
            capped[up] = [b for b in (lo, end) if b]

    # chains: upper target bone -> (lower bone, source root, mid, end), lengths and scale
    chains, chain_len, chain_scale = {}, {}, {}
    for up_r, lo_r, end_r in R.CHAINS.values():
        up, lo = roles.get(up_r), roles.get(lo_r)
        sroot, smid, send = s_of.get(up_r), s_of.get(lo_r), s_of.get(end_r)
        if not (up and lo and up in rest_world and lo in rest_world and sroot and smid and send):
            continue
        if not all(j in W[f0] for j in (sroot, smid, send)):
            continue
        p = lambda j: W[f0][j][:3, 3]
        sl = float(np.linalg.norm(p(smid) - p(sroot)) + np.linalg.norm(p(send) - p(smid)))
        tl1 = float(np.linalg.norm(rest_world[up][:3, 3] - rest_world[lo][:3, 3]))
        tl2 = float(rig["length"][lo]) * scale_x
        chains[up] = (lo, sroot, smid, send)
        chain_len[up] = (tl1, tl2)
        chain_scale[up] = (tl1 + tl2) / max(sl, 1e-6)
    if s["mode"] == "ik":
        info.append(f"IK chains {sorted(chains)} lengths "
                    f"{ {k: (round(a, 3), round(b, 3)) for k, (a, b) in chain_len.items()} }")

    travel = float(rig["height"]) / max(float(src["height_f0"]), 1e-6)
    ref_root = W[f0][root_src][:3, 3].copy() if root_src else np.zeros(3)

    worst = {}
    rot = {t: [] for _, _, t in use}
    loc = {root_t: []} if root_t in rot else {}
    order = rig["order"]

    for frame in frames:
        Wf = W[frame]
        posed = {}

        def fk(b):
            """World matrix of b this frame: set if driven already, else rest-relative to its parent."""
            if b in posed:
                return posed[b]
            p = parent.get(b)
            m = rest_world[b] if not p else fk(p) @ rest_rel[b]
            return m

        ride, aim_at = {}, {}
        for role, sj, t in use:
            m = Wf[sj]
            delta = ncols(m[:3, :3]) @ ref_inv[sj]
            if t in clavicles and s["clavicle_damp"] < 1.0:
                delta = quat_to_mat(slerp_from_identity(mat_to_quat(delta), s["clavicle_damp"]))
            want = delta @ bind_rot[t]
            a = fk(t)[:3, 3]
            if s["mode"] == "ik" and t in chains:
                lo, sroot, smid, send = chains[t]
                hips = fk(root_t)[:3, 3] if root_t else a
                sh = Wf[root_src][:3, 3] if root_src else np.zeros(3)
                sa = Wf[sroot][:3, 3]
                k = chain_scale[t]
                lim_t = a + (Wf[send][:3, 3] - sa) * k
                lim_p = a + (Wf[smid][:3, 3] - sa) * k
                bod_t = hips + (Wf[send][:3, 3] - sh) * travel
                bod_p = hips + (Wf[smid][:3, 3] - sh) * travel
                target = lim_t + (bod_t - lim_t) * s["ik_body"]
                pole = lim_p + (bod_p - lim_p) * s["ik_body"]
                if t in capped:
                    to = target - a
                    elev = math.degrees(math.asin(max(-1.0, min(1.0, unit(to)[2]))))
                    if elev > s["arm_cap"]:
                        horiz = np.array([to[0], to[1], 0.0])
                        if np.linalg.norm(horiz) > 1e-6:
                            ax = np.cross(unit(horiz), Z)
                            if np.linalg.norm(ax) > 1e-6:
                                to = axis_angle(unit(ax), -math.radians(elev - s["arm_cap"])) @ to
                                target = a + to
                l1, l2 = chain_len[t]
                mid = two_bone_ik(a, target, pole, l1, l2)
                want = aim_dir(want, mid - a)
                aim_at[lo] = (mid, target)
            elif s["mode"] == "ik" and t in aim_at:
                mid, target = aim_at[t]
                want = aim_dir(want, target - mid)
            elif t in capped:
                want, r = cap_elevation(want, s["arm_cap"])
                for child in capped[t]:
                    ride[child] = r
            elif ride.get(t) is not None:
                want = ride[t] @ want
            if t == root_t:
                here = rest_head[t] if not s["root_loc"] else rest_head[t] + (m[:3, 3] - ref_root) * travel
            else:
                here = a
            posed[t] = translate(want, here)

        # pose basis for the driven bones: basis = rest_local^-1 . parent_pose^-1 . pose (armature space)
        for _, _, t in use:
            pose_arm = tw_inv @ posed[t]
            p = parent.get(t)
            if p:
                par_arm = tw_inv @ fk(p)
                basis = np.linalg.inv(rest_rel[t]) @ np.linalg.inv(par_arm) @ pose_arm
                # rest_rel is world-relative; armature-relative is the same matrix since tw cancels
            else:
                basis = np.linalg.inv(tw_inv @ rest_world[t]) @ pose_arm
            q = mat_to_quat(basis[:3, :3])
            if rot[t] and float(np.dot(rot[t][-1], q)) < 0:
                q = -q
            rot[t].append(q)
            if t == root_t:
                loc[t].append(basis[:3, 3].copy())

        if PC.sample(frame, f0, f1):
            src_pos = {sj: Wf[sj][:3, 3] for _, sj, _ in use}
            tgt_pos = {t: posed[t][:3, 3] for _, _, t in use}
            PC.measure(segs, src_pos, tgt_pos, worst, frame)

    jaw = roles.get("jaw")
    jaw_q = None
    if jaw and jaw in rest_world and s["jaw_closed"] > 0:
        axis = unit(np.linalg.inv(rest_world[jaw][:3, :3]) @ np.array([1.0, 0.0, 0.0]))
        jaw_q = quat_axis_angle(axis, math.radians(-s["jaw_closed"]))

    src_ref = {r: W[f0][sj][:3, 3] for r, sj, _ in use}
    tgt_ref = {r: rest_world[t][:3, 3] for r, _, t in use}
    return {
        "frames": frames,
        "rot": {t: np.array(v) for t, v in rot.items()},
        "loc": {t: np.array(v) for t, v in loc.items()},
        "jaw": None if jaw_q is None else {"bone": jaw, "quat": jaw_q},
        "pose_check": PC.report(worst, use),
        "segments": len(segs),
        "proportions": proportions.measure(src_ref, tgt_ref),
        "info": info + [f"travel {travel:.4f}", f"driving {len(use)} bones"],
    }
