"""Stage 3: rigged model → animated model with actions named idle/move/attack/….

Modes (``stages.animate.mode``):
  passthrough  the source already carries its clips (a downloaded animated GLB,
               a hand-animated .blend). Nothing to do beyond confirming it exists;
               ``actions.<name>.source`` in the boss config maps clip names.
  procedural   Phase 2 — role-keyed bpy recipes (hover, flap, breathe, lunge)
               baked onto the rig from rig/bones.json. Not built yet.
"""
from __future__ import annotations

from pathlib import Path


def run(cfg: dict, workdir: Path) -> Path:
    stage = cfg.get("stages", {}).get("animate", {})
    mode = stage.get("mode", "procedural")
    if mode == "passthrough":
        source = workdir / cfg["source"]
        if not source.exists():
            raise SystemExit(f"animate passthrough: {source} missing")
        print("  animate: passthrough", source.name)
        return source
    if mode == "procedural":
        raise SystemExit("animate mode 'procedural' is Phase 2 (see PLAN.md); use mode 'passthrough' for now")
    raise SystemExit(f"unknown animate mode {mode!r}")
