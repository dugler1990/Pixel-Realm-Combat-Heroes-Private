"""Stage 3: rigged model → animated model with actions named idle/move/attack.

Modes (``stages.animate.mode``):
  passthrough  the source already carries its clips (a downloaded animated GLB,
               a hand-animated .blend). Nothing to do beyond confirming it exists;
               ``actions.<name>.source`` in the boss config maps clip names.
  procedural   role-keyed bpy recipes (breathe / stomp walk / lunge) baked onto the rig by
               ``animate_procedural.py`` (runs under .venv-bpy). Needs:
                 stages.animate.rigged  — rigged GLB, relative to the workdir
                 stages.animate.roles   — bone_roles.json, relative to the workdir
                 stages.animate.params  — optional amplitude overrides (dict or a json path)
               Writes <workdir>/animate/animated.blend, which the render stage reads.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import bpy_python

HERE = Path(__file__).resolve().parent


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
        rigged = workdir / stage.get("rigged", "rig/rigged.glb")
        roles = workdir / stage.get("roles", "rig/bone_roles.json")
        for p in (rigged, roles):
            if not p.exists():
                raise SystemExit(f"animate procedural: {p} missing")
        out = workdir / "animate"
        out.mkdir(parents=True, exist_ok=True)
        args = [str(bpy_python(HERE)), str(HERE / "animate_procedural.py"), str(rigged), str(roles), str(out)]
        params = stage.get("params")
        if params:
            if isinstance(params, dict):
                pp = out / "params.json"
                pp.write_text(json.dumps(params, indent=1), encoding="utf-8")
                params = pp
            args.append(str(workdir / params) if not Path(params).is_absolute() else str(params))
        subprocess.run(args, check=True)
        blend = out / "animated.blend"
        print("  animate →", blend)
        return blend
    raise SystemExit(f"unknown animate mode {mode!r}")
