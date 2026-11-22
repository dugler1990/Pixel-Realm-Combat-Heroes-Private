"""Rig-step registry. A step module declares:

  NAME, DOC, KIND ("weights" | "bone_set" | "auto": decided by comparing bone sets), LANE ("local" | "pod"),
  SETTINGS  [Setting]            the page builds the form from these
  CHECKS    {check: [rule...]}   rule = (metric, op, value, gate) on the numbers the check returns
  run(ctx) -> {"glb": Path | None (None = same glb as the input), "roles": {role: bone}}

A new technique is a new module here; nothing else changes.
"""
from __future__ import annotations

from . import add_bone, manual, move_pivot, rehome_orphans, reweight, roles_walk

STEPS = {m.NAME: m for m in (roles_walk, reweight, rehome_orphans, move_pivot, add_bone, manual)}


def get(name: str):
    if name not in STEPS:
        raise ValueError(f"step {name!r}, have {sorted(STEPS)}")
    return STEPS[name]
