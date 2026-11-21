"""Numbers that make a copied pose look wrong. Transfer reads override or measured."""
from __future__ import annotations

import math

# A child role gives the bone a direction. neck2 is not given a bone.
_CHILD = {
    "root": "spine",
    "spine": "spine2",
    "spine2": "chest",
    "chest": "neck",
    "neck": "head",
    "clavicle.L": "upper_arm.L",
    "upper_arm.L": "forearm.L",
    "forearm.L": "hand.L",
    "clavicle.R": "upper_arm.R",
    "upper_arm.R": "forearm.R",
    "forearm.R": "hand.R",
    "thigh.L": "shin.L",
    "shin.L": "ankle.L",
    "ankle.L": "foot.L",
    "thigh.R": "shin.R",
    "shin.R": "ankle.R",
    "ankle.R": "foot.R",
}
# Above this, the bone is bind-skipped. The head (crown axis versus face axis) is the known case.
AXIS_SKIP_DEG = 45.0
# Human recipe grows these when the source has them and the rig does not.
HUMAN_ADD = ("eye.L", "eye.R", "jaw")


def _field(measured, override=None):
    return {"measured": measured, "override": override}


def _dist(a, b) -> float:
    return math.dist(a, b)


def _span(world: dict) -> float:
    if len(world) < 2:
        return 0.0
    xs, ys, zs = zip(*world.values())
    return max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def _shoulder(world) -> float | None:
    if "clavicle.L" in world and "clavicle.R" in world:
        return _dist(world["clavicle.L"], world["clavicle.R"])
    if "upper_arm.L" in world and "upper_arm.R" in world:
        return _dist(world["upper_arm.L"], world["upper_arm.R"])
    return None


def _arm(world) -> float | None:
    total = 0.0
    n = 0
    for side in (".L", ".R"):
        chain = [f"upper_arm{side}", f"forearm{side}", f"hand{side}"]
        if all(c in world for c in chain):
            total += _dist(world[chain[0]], world[chain[1]]) + _dist(world[chain[1]], world[chain[2]])
            n += 1
    return total / n if n else None


def _angle(a, b) -> float:
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))
    return math.degrees(math.acos(dot))


def _dir(world, role):
    child = _CHILD.get(role)
    if not child or role not in world or child not in world:
        return None
    ax, ay, az = world[role]
    bx, by, bz = world[child]
    v = (bx - ax, by - ay, bz - az)
    n = math.dist((0, 0, 0), v)
    if n < 1e-8:
        return None
    return (v[0] / n, v[1] / n, v[2] / n)


def _by_role(paired, world_of_joint: dict) -> dict:
    out = {}
    for p in paired:
        w = world_of_joint.get(p["source"])
        if w is not None:
            out[p["role"]] = w
    return out


def fit(matched: dict, source_world: dict, target_world: dict, recipe: str) -> dict:
    """source_world / target_world: joint or bone name → (x, y, z), same space as the skeleton offsets."""
    if recipe not in ("human", "creature"):
        raise ValueError(recipe)
    src = {}
    dst = {}
    for p in matched["paired"]:
        if p["source"] in source_world:
            src[p["role"]] = source_world[p["source"]]
        if p["target"] in target_world:
            dst[p["role"]] = target_world[p["target"]]
    sw, dw = _shoulder(src), _shoulder(dst)
    barrel = None
    if sw and dw and sw > 1e-8:
        barrel = max(0.0, min(1.0, dw / sw))
    sh, dh = _span(src), _span(dst)
    sa, da = _arm(src), _arm(dst)
    reach = None
    if sa and da and sh > 1e-8 and dh > 1e-8:
        reach = (da / dh) / (sa / sh)
    skips = []
    errors = {}
    for role in sorted(set(src) & set(dst)):
        a, b = _dir(src, role), _dir(dst, role)
        if not a or not b:
            continue
        deg = round(_angle(a, b), 2)
        errors[role] = deg
        if deg > AXIS_SKIP_DEG:
            skips.append(role)
    foot = _dir(dst, "ankle.L") or _dir(dst, "ankle.R")
    # A plantigrade toe bone lies along the ground. A digitigrade metatarsus stands up.
    mode = None
    if foot:
        mode = "plantigrade" if abs(foot[1]) < 0.45 else "digitigrade"
    arm_cap = 35.0 if recipe == "creature" else 90.0
    return {
        "barrel_chest": _field(None if barrel is None else round(barrel, 4)),
        "limb_reach": _field(None if reach is None else round(reach, 4)),
        "axis_error": _field(errors),
        "bind_skip": skips,
        "feet": _field(mode),
        "arm_cap": _field(arm_cap),
        "bind": _field(None),
    }


def knob_env(patch: dict) -> dict[str, str]:
    """Overrides the bake already understands.

    barrel_chest is how much of the sculpted shoulder width to keep (1 = keep it).
    CLAVICLE_DAMP is how much of the source clavicle rotation to copy (1 = copy all, damping off).
    The two face opposite directions, so the env value is 1 - barrel_chest.
    limb_reach is measured here and not passed: IK_BODY is a different dial.
    """
    env = {}
    if patch.get("barrel_chest") is not None:
        kept = max(0.0, min(1.0, float(patch["barrel_chest"])))
        env["CLAVICLE_DAMP"] = f"{1.0 - kept:.4f}"
    if patch.get("arm_cap") is not None:
        env["ARM_ELEV_CAP"] = str(float(patch["arm_cap"]))
    if patch.get("bind_match") is not None:
        env["BIND_MATCH"] = "1" if patch["bind_match"] in (True, 1, "1", "true") else "0"
    return env


def apply_patch(fit_obj: dict, patch: dict) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) and "measured" in v else v) for k, v in fit_obj.items()}
    for key, value in patch.items():
        if key in out and isinstance(out[key], dict) and "measured" in out[key]:
            out[key]["override"] = value
    return out


def edits(matched: dict, source_roles: dict[str, str], source_world: dict, recipe: str) -> list[dict]:
    """Bones to add before motion. Weights stay on the head. neck2 is never added.

    A creature that already has a jaw does not grow a second one: this recipe adds nothing.
    """
    if recipe != "human":
        return []
    have = {p["role"] for p in matched["paired"]}
    name_of = {role: name for name, role in source_roles.items()}
    head = name_of.get("head")
    if head is None or head not in source_world:
        return []
    hx, hy, hz = source_world[head]
    out = []
    for role in HUMAN_ADD:
        if role in have or role not in matched["missing"]:
            continue
        joint = name_of.get(role)
        if joint is None or joint not in source_world:
            continue
        x, y, z = source_world[joint]
        out.append({
            "op": "add_bone",
            "role": role,
            "parent": "head",
            "offset": [round(x - hx, 5), round(y - hy, 5), round(z - hz, 5)],
        })
    return out
