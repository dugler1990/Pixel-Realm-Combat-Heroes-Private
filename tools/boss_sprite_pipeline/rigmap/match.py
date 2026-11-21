"""Match is equality of anatomical roles."""
from __future__ import annotations


def match(source: dict[str, str], target: dict[str, str], target_bones: list[str] | None = None) -> dict:
    src_of = {}
    for name, role in source.items():
        src_of.setdefault(role, name)
    dst_of = {}
    for name, role in target.items():
        dst_of.setdefault(role, name)
    paired = []
    for role in sorted(set(src_of) & set(dst_of)):
        paired.append({"role": role, "source": src_of[role], "target": dst_of[role]})
    missing = sorted(set(src_of) - set(dst_of))
    labelled = set(target)
    bones = target_bones if target_bones is not None else list(target)
    unmapped = sorted(b for b in bones if b not in labelled)
    return {
        "paired": paired,
        "missing": missing,
        "unmapped": unmapped,
        "roles": [p["role"] for p in paired],
    }
