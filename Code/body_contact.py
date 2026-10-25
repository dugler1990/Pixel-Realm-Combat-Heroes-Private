"""3D capsule contact on the ground plane for mesh bodies and upright sprites.

No pygame / Settings / mesh_boss imports — mesh_boss imports this module.
"""
from __future__ import annotations

import math
import time
from collections import namedtuple

import numpy as np

Body = namedtuple("Body", "A B R feet")
Contact = namedtuple("Contact", "touching normal a_hits")

CONTACT_STATS = {"contacts": 0, "ms": 0.0}

_EPS = 1e-8


def model_to_ground(points, pivot, facing_deg, scale):
    """Model points to ground pixels relative to the feet (gx, gy, gz)."""
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim == 1:
        pts = pts.reshape(1, 3)
    pivot = np.asarray(pivot, dtype=np.float64)
    yaw = math.radians(float(facing_deg))
    cy, sy = math.cos(yaw), math.sin(yaw)
    p = pts - pivot
    xr = p[:, 0] * cy - p[:, 1] * sy
    yr = p[:, 0] * sy + p[:, 1] * cy
    s = float(scale)
    gx = xr * s
    gy = -yr * s
    gz = p[:, 2] * s
    return np.column_stack([gx, gy, gz])


def ground_to_screen(g, elevation_deg):
    """Ground pixels (N,3) to screen offsets from the feet (N,2)."""
    g = np.asarray(g, dtype=np.float64)
    if g.ndim == 1:
        g = g.reshape(1, 3)
    elev = math.radians(float(elevation_deg))
    se, ce = math.sin(elev), math.cos(elev)
    sx = g[:, 0]
    sy = g[:, 1] * se - g[:, 2] * ce
    return np.column_stack([sx, sy])


def closest_points_segments(P0, P1, Q0, Q1):
    """Ericson 5.1.9 ClosestPtSegmentSegment, vectorized (N,1,3) x (1,M,3).

    Returns (C1, C2, dist) with shapes (N,M,3), (N,M,3), (N,M).
    """
    P0 = np.asarray(P0, dtype=np.float64)
    P1 = np.asarray(P1, dtype=np.float64)
    Q0 = np.asarray(Q0, dtype=np.float64)
    Q1 = np.asarray(Q1, dtype=np.float64)

    d1 = P1 - P0
    d2 = Q1 - Q0
    r = P0 - Q0

    a = np.sum(d1 * d1, axis=-1)  # (N,1)
    e = np.sum(d2 * d2, axis=-1)  # (1,M)
    f = np.sum(d2 * r, axis=-1)   # (N,M)
    cdot = np.sum(d1 * r, axis=-1)
    bdot = np.sum(d1 * d2, axis=-1)

    # Broadcast a,e to (N,M)
    a_nm = np.broadcast_to(a, f.shape).copy()
    e_nm = np.broadcast_to(e, f.shape).copy()

    s = np.zeros_like(f)
    t = np.zeros_like(f)

    both_pt = (a_nm <= _EPS) & (e_nm <= _EPS)
    a_pt = (a_nm <= _EPS) & (e_nm > _EPS)
    e_pt = (e_nm <= _EPS) & (a_nm > _EPS)
    gen = (a_nm > _EPS) & (e_nm > _EPS)

    # a degenerates: s=0, t = clamp(f/e, 0, 1)
    t = np.where(a_pt, np.clip(f / np.maximum(e_nm, _EPS), 0.0, 1.0), t)
    # e degenerates: t=0, s = clamp(-c/a, 0, 1)
    s = np.where(e_pt, np.clip(-cdot / np.maximum(a_nm, _EPS), 0.0, 1.0), s)

    # General case
    denom = a_nm * e_nm - bdot * bdot
    s_unconstrained = np.where(
        np.abs(denom) > _EPS,
        (bdot * f - cdot * e_nm) / np.where(np.abs(denom) > _EPS, denom, 1.0),
        0.0,
    )
    s_clamped = np.clip(s_unconstrained, 0.0, 1.0)
    t_raw = (bdot * s_clamped + f) / np.maximum(e_nm, _EPS)

    t_lo = gen & (t_raw < 0.0)
    t_hi = gen & (t_raw > 1.0)
    t_ok = gen & ~(t_lo | t_hi)

    s = np.where(t_ok, s_clamped, s)
    t = np.where(t_ok, t_raw, t)
    s = np.where(t_lo, np.clip(-cdot / np.maximum(a_nm, _EPS), 0.0, 1.0), s)
    t = np.where(t_lo, 0.0, t)
    s = np.where(t_hi, np.clip((bdot - cdot) / np.maximum(a_nm, _EPS), 0.0, 1.0), s)
    t = np.where(t_hi, 1.0, t)

    # both points already s=t=0
    s = np.where(both_pt, 0.0, s)
    t = np.where(both_pt, 0.0, t)

    C1 = P0 + d1 * s[..., None]
    C2 = Q0 + d2 * t[..., None]
    diff = C1 - C2
    dist = np.sqrt(np.maximum(np.sum(diff * diff, axis=-1), 0.0))
    return C1, C2, dist


def _world_to_ground_feet(feet_world, elevation_deg):
    fx, fy = float(feet_world[0]), float(feet_world[1])
    se = math.sin(math.radians(float(elevation_deg)))
    if abs(se) < _EPS:
        se = _EPS
    return np.array([fx, fy / se], dtype=np.float64)


def upright_body(feet_world, height_true_px, radius_px, elevation_deg):
    """One vertical capsule standing on feet_world (world pixels)."""
    r = max(0.0, float(radius_px))
    h = max(0.0, float(height_true_px))
    feet_g = _world_to_ground_feet(feet_world, elevation_deg)
    z0 = r
    z1 = max(r, h - r)
    A = np.array([[feet_g[0], feet_g[1], z0]], dtype=np.float64)
    B = np.array([[feet_g[0], feet_g[1], z1]], dtype=np.float64)
    R = np.array([r], dtype=np.float64)
    return Body(A, B, R, feet_g)


def mesh_contact(a, b, elevation_deg):
    """Closest capsule contact between two Bodies. Normal points toward a (self)."""
    t0 = time.perf_counter()
    n = int(a.A.shape[0])
    m = int(b.A.shape[0])
    if n == 0 or m == 0:
        CONTACT_STATS["contacts"] += 1
        CONTACT_STATS["ms"] += (time.perf_counter() - t0) * 1000.0
        return Contact(False, None, np.zeros(n, dtype=bool))

    P0 = a.A[:, None, :]
    P1 = a.B[:, None, :]
    Q0 = b.A[None, :, :]
    Q1 = b.B[None, :, :]
    C1, C2, dist = closest_points_segments(P0, P1, Q0, Q1)
    rad = a.R[:, None] + b.R[None, :]
    penetration = rad - dist
    touching_mask = penetration > 0.0
    touching = bool(np.any(touching_mask))
    a_hits = np.any(touching_mask, axis=1) if touching else np.zeros(n, dtype=bool)

    normal = None
    if touching:
        flat = penetration.ravel()
        idx = int(np.argmax(flat))
        i, j = divmod(idx, m)
        # Vector from b's closest point to a's — points toward a
        gvec = C1[i, j] - C2[i, j]
        gx, gy = float(gvec[0]), float(gvec[1])
        if math.hypot(gx, gy) < 1e-6:
            gx = float(a.feet[0] - b.feet[0])
            gy = float(a.feet[1] - b.feet[1])
        if math.hypot(gx, gy) < 1e-6:
            gx, gy = 1.0, 0.0
        se = math.sin(math.radians(float(elevation_deg)))
        wx, wy = gx, gy * se
        length = math.hypot(wx, wy)
        if length < 1e-12:
            normal = (1.0, 0.0)
        else:
            normal = (wx / length, wy / length)

    CONTACT_STATS["contacts"] += 1
    CONTACT_STATS["ms"] += (time.perf_counter() - t0) * 1000.0
    return Contact(touching, normal, a_hits)


def is_mesh(obj):
    owner = getattr(obj, "owner", None) or obj
    return getattr(owner, "mesh_boss", None) is not None


def collision_body(obj, elevation_deg):
    """Build a Body from a live entity, HashableRect with owner, or bare snapshot."""
    owner = getattr(obj, "owner", None) or obj
    elev = float(elevation_deg)

    boss = getattr(owner, "mesh_boss", None)
    if boss is not None:
        pack = boss.pack
        A_model, B_model = pack.posed_capsule_ends(boss.frame_index)
        height_px = float(getattr(owner, "mesh_height_px", 650) or 650)
        scale = height_px / max(pack.height_units, 1e-6)
        get_facing = getattr(owner, "get_facing_deg", None)
        facing = float(get_facing()) if callable(get_facing) else 0.0
        Ag = model_to_ground(A_model, pack.pivot, facing, scale)
        Bg = model_to_ground(B_model, pack.pivot, facing, scale)
        hitbox = getattr(owner, "hitbox", None)
        if hitbox is not None:
            feet_world = hitbox.midbottom
        else:
            rect = getattr(owner, "rect", None)
            feet_world = rect.midbottom if rect is not None else (0.0, 0.0)
        feet_g = _world_to_ground_feet(feet_world, elev)
        Ag = Ag + np.array([feet_g[0], feet_g[1], 0.0])
        Bg = Bg + np.array([feet_g[0], feet_g[1], 0.0])
        R = np.asarray(pack.capsule_radii, dtype=np.float64) * scale
        return Body(Ag, Bg, R, feet_g)

    hitbox = getattr(owner, "hitbox", None)
    if hitbox is not None:
        get_reach = getattr(owner, "get_collision_reach_px", None)
        if callable(get_reach):
            reach = float(get_reach())
        else:
            reach = float(getattr(owner, "collision_reach_px", 0.0) or 0.0)
        ce = math.cos(math.radians(elev))
        height_true = reach / ce if abs(ce) > _EPS else reach
        radius = float(getattr(owner, "collision_ground_radius_px", 0.0) or 0.0)
        if radius <= 0.0:
            rect = getattr(owner, "rect", None)
            radius = float(rect.width) / 4.0 if rect is not None else 8.0
        return upright_body(hitbox.midbottom, height_true, radius, elev)

    # Bare snapshot: HashableRect with only rect
    rect = getattr(obj, "rect", None)
    if rect is None:
        raise ValueError(f"collision_body: cannot build Body from {type(obj)!r}")
    ce = math.cos(math.radians(elev))
    height_true = float(rect.height) / ce if abs(ce) > _EPS else float(rect.height)
    radius = float(rect.width) / 4.0
    return upright_body(rect.midbottom, height_true, radius, elev)
