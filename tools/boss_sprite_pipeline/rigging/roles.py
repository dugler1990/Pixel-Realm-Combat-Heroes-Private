"""The anatomical role list, the chains, and the conversion of old roles files into it.

A rig version stores its roles canonically: role -> bone name, flat. The off-by-one keys of the
old files (anun_roles.py's `elbow` is the upper arm, `wrist` the forearm; the demon's key `neck` is
the skull and `head` the snout) are translated here, once, and nowhere else.
"""
from __future__ import annotations

SIDES = (".L", ".R")

CORE = ["root", "spine", "spine2", "chest", "neck", "head"]
LIMB = ["clavicle", "upper_arm", "forearm", "hand", "thigh", "shin", "ankle", "foot"]
FACE = ["jaw", "eye.L", "eye.R"]
ROLES = CORE + [p + s for p in LIMB for s in SIDES] + FACE
# Recorded when present, never required: neck2, toes, fingers, wings, tail, the demon's snout.
OPTIONAL_PREFIXES = ("neck2", "toe.", "fingers.", "wing.", "tail.", "snout")

# (upper, lower, end): IK chains and the bones the arm cap rides down.
CHAINS = {f"arm{s}": (f"upper_arm{s}", f"forearm{s}", f"hand{s}") for s in SIDES}
CHAINS.update({f"leg{s}": (f"thigh{s}", f"shin{s}", f"ankle{s}") for s in SIDES})
CLAVICLES = tuple(f"clavicle{s}" for s in SIDES)
UPPER_ARMS = tuple(f"upper_arm{s}" for s in SIDES)

# old roles-file keys -> role
_ARM = {"shoulder": "clavicle", "elbow": "upper_arm", "wrist": "forearm", "hand": "hand"}
_LEG = {"hip": "thigh", "knee": "shin", "ankle": "ankle", "foot": "foot", "toe": "toe"}
_SIDE = {"_l": ".L", "_r": ".R"}

STYLES = ("anun", "demon_hand")


def canonical(old: dict, style: str) -> dict[str, str]:
    """An old roles file -> {role: bone}.

    anun: written by rigfix/anun_roles.py; `neck` is a neck, `head` the head.
    demon_hand: the demon's hand-labelled file; the key `neck` is the skull, `head` the snout.
    """
    if style not in STYLES:
        raise ValueError(f"style {style!r}, want one of {STYLES}")
    out: dict[str, str] = {}

    def put(role, bone):
        if isinstance(bone, str) and bone:
            out[role] = bone

    for key in ("root", "spine", "spine2", "chest", "jaw"):
        put(key, old.get(key))
    if style == "anun":
        put("neck", old.get("neck"))
        put("head", old.get("head"))
    else:
        put("head", old.get("neck"))
        put("snout", old.get("head"))
    for side, suffix in _SIDE.items():
        arm = old.get("arm" + side)
        if isinstance(arm, dict):
            for key, role in _ARM.items():
                put(role + suffix, arm.get(key))
            for i, bone in enumerate(arm.get("fingers") or [], 1):
                put(f"fingers{suffix}.{i}", bone)
        leg = old.get("leg" + side)
        if isinstance(leg, dict):
            for key, role in _LEG.items():
                put(role + suffix, leg.get(key))
        wing = old.get("wing" + side)
        if isinstance(wing, dict):
            put(f"wing{suffix}", wing.get("arm"))
            put(f"wing{suffix}.tip", wing.get("fan"))
    for i, bone in enumerate(old.get("tail") or [], 1):
        put(f"tail.{i}", bone)
    return out


def bone_of(roles: dict[str, str], role: str) -> str | None:
    return roles.get(role)


def role_of_bone(roles: dict[str, str]) -> dict[str, str]:
    return {b: r for r, b in roles.items()}


def is_optional(role: str) -> bool:
    return role.startswith(OPTIONAL_PREFIXES)
