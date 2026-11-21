"""Pose check: each driven bone's segment, joint to its nearest driven child joint, on the mesh against
the same segment on the stick, in world space. Positions, not bone axes, so roll and axis conventions
do not enter. Measures how well motion transfers, not mesh damage.

barb_hit_heavy_01 (2026-11-21): human template peaks 29.4 (neck); bind on the hips 149.3 (hips);
bind off 153.3 (right forearm).
"""
from __future__ import annotations

import math

import numpy as np

LIMIT_DEG = 40.0
EVERY = 5


def _paired_parent(name: str, parent: dict, names: set) -> str | None:
    p = parent.get(name)
    while p is not None and p not in names:
        p = parent.get(p)
    return p


def _next(role: str) -> list[str]:
    """The child a segment runs to when a joint has several (the chest has a neck and two clavicles)."""
    side = role[-2:] if role[-2:] in (".L", ".R") else ""
    base = role[:-2] if side else role
    chain = {"root": ["spine"], "spine": ["spine2", "chest"], "spine2": ["chest"], "chest": ["neck", "head"],
             "neck": ["head"], "clavicle": ["upper_arm"], "upper_arm": ["forearm"], "forearm": ["hand"],
             "thigh": ["shin"], "shin": ["ankle"], "ankle": ["foot"]}
    return [c + side if c not in ("spine", "spine2", "chest", "neck", "head") else c
            for c in chain.get(base, [])]


def segments(use, src_parent: dict, tgt_parent: dict) -> list[tuple[str, str, str, str, str]]:
    """[(role, s, t, s2, t2)]: t2 is t's driven child along the body's chain (chest -> neck, clavicle ->
    upper arm), else its first driven child by role name; s2 the matching source joint.

    2026-11-21: the old check took whichever child came first in its bone table, so the demon's chest
    measured to the head (11.1) and the barb's to the left clavicle (25.8)."""
    tset = {t for _, _, t in use}
    sset = {s for _, s, _ in use}
    out = []
    for role, s, t in use:
        kids = {r2: (s2, t2) for r2, s2, t2 in use
                if _paired_parent(t2, tgt_parent, tset) == t and _paired_parent(s2, src_parent, sset) == s}
        if not kids:
            continue
        pick = next((c for c in _next(role) if c in kids), sorted(kids)[0])
        out.append((role, s, t, kids[pick][0], kids[pick][1]))
    return out


def sample(frame: int, f0: int, f1: int) -> bool:
    return (frame - f0) % EVERY == 0 or frame == f1


def measure(segs, src_pos: dict, tgt_pos: dict, worst: dict, frame: int) -> None:
    """Update worst[t] = (deg, frame) with this frame."""
    for _, s, t, s2, t2 in segs:
        ds = np.asarray(src_pos[s2]) - np.asarray(src_pos[s])
        dt = np.asarray(tgt_pos[t2]) - np.asarray(tgt_pos[t])
        ns, nt = np.linalg.norm(ds), np.linalg.norm(dt)
        if ns < 1e-6 or nt < 1e-6:
            continue
        deg = math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(ds, dt) / (ns * nt))))))
        if deg > worst.get(t, (0.0, 0))[0]:
            worst[t] = (deg, frame)


def report(worst: dict, use) -> dict:
    """{"bones": {"src>tgt": [deg, frame]} worst first, "worst", "fail": [...], "limit"}."""
    src_of = {t: s for _, s, t in use}
    role_of = {t: r for r, _, t in use}
    rows = sorted(worst.items(), key=lambda kv: -kv[1][0])
    bones = {f"{src_of[t]}>{t}": [round(d, 1), f] for t, (d, f) in rows}
    by_role = {role_of[t]: round(d, 1) for t, (d, _) in rows}
    fail = [k for k, (d, _) in bones.items() if d > LIMIT_DEG]
    w = rows[0] if rows else None
    return {"bones": bones, "by_role": by_role, "limit": LIMIT_DEG, "fail": fail,
            "worst": None if not w else {"bone": f"{src_of[w[0]]}>{w[0]}", "deg": round(w[1][0], 1),
                                         "frame": w[1][1]}}
