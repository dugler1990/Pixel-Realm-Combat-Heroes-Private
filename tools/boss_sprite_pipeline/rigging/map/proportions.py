"""Body proportions of the target against the source, measured at the reference pose.

Never at the BVH rest: Kimodo's rest lies along +X (every bone (1,0,0)). Results go in the bake's
run.json, not the character file, until a shared idle is the reference pose.

axis_error / bind_skip from rest directions were dropped (2026-11-21): ~90 deg on every bone at the
Kimodo rest, and blind to the hip fold, which is a bone-axis mismatch.
"""
from __future__ import annotations

import math


def _dist(a, b) -> float:
    return math.dist(a, b)


def _height(world: dict) -> float:
    if len(world) < 2:
        return 0.0
    zs = [p[2] for p in world.values()]
    return max(zs) - min(zs)


def _shoulder(w) -> float | None:
    # shoulder joints (upper-arm heads), not clavicle heads: SOMA's clavicles start near the
    # midline, UniRig's do not, which read as 4.4x wider on the barb (2026-11-21)
    for a, b in (("upper_arm.L", "upper_arm.R"), ("clavicle.L", "clavicle.R")):
        if a in w and b in w:
            return _dist(w[a], w[b])
    return None


def _chain(w, names) -> float | None:
    if not all(n in w for n in names):
        return None
    return sum(_dist(w[names[i]], w[names[i + 1]]) for i in range(len(names) - 1))


def _avg(vals):
    vals = [v for v in vals if v]
    return sum(vals) / len(vals) if vals else None


def measure(source_world: dict[str, tuple], target_world: dict[str, tuple]) -> dict:
    """source_world / target_world: role -> joint head position (z up), same pose convention.

    shoulder_ratio: target shoulder width / source, both over height.
    arm_ratio / leg_ratio: limb length over height, target / source. The IK body blend is meant to
    compensate arm_ratio (a hip-anchored target lands inside a shorter reach).
    """
    sh, th = _height(source_world), _height(target_world)
    out = {"source_height": round(sh, 4), "target_height": round(th, 4)}
    if sh < 1e-8 or th < 1e-8:
        return out

    def ratio(fn):
        s, t = fn(source_world), fn(target_world)
        return None if not s or not t else round((t / th) / (s / sh), 4)

    out["shoulder_ratio"] = ratio(_shoulder)
    out["arm_ratio"] = ratio(lambda w: _avg([_chain(w, [f"upper_arm{x}", f"forearm{x}", f"hand{x}"])
                                            for x in (".L", ".R")]))
    out["leg_ratio"] = ratio(lambda w: _avg([_chain(w, [f"thigh{x}", f"shin{x}", f"ankle{x}"])
                                            for x in (".L", ".R")]))
    return out
