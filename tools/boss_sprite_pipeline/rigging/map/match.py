"""Match is equality of roles.

source: {joint: role} from a source labeller. target: {role: bone} from a rig version.
"""
from __future__ import annotations

from ..roles import is_optional


def match(source: dict[str, str], target: dict[str, str], target_bones: list[str] | None = None,
          static: set[str] | frozenset = frozenset()) -> dict:
    """paired: role on both sides (static source joints excluded: nothing moves them).
    missing: source has it, target does not. unmapped: target bones with no role (stay at rest)."""
    src_of = {}
    for name, role in source.items():
        src_of.setdefault(role, name)
    paired = [{"role": r, "source": src_of[r], "target": target[r]}
              for r in sorted(set(src_of) & set(target)) if r not in static]
    missing = sorted(set(src_of) - set(target))
    labelled = set(target.values())
    bones = target_bones if target_bones is not None else list(labelled)
    unmapped = sorted(b for b in bones if b not in labelled)
    return {
        "paired": paired,
        "missing": missing,
        "missing_required": sorted(r for r in missing if not is_optional(r)),
        "unmapped": unmapped,
        "static": sorted(r for r in static if r in src_of and r in target),
        "roles": [p["role"] for p in paired],
    }
