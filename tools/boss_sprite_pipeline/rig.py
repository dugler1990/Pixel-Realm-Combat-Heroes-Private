"""Stage 2: ``mesh/raw.glb`` → ``rig/rigged.glb`` + ``rig/bones.json``."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .backends import get_backend

HERE = Path(__file__).resolve().parent


def run(cfg: dict, workdir: Path, gpu) -> Path:
    stage = cfg.get("stages", {}).get("rig", {})
    backend = get_backend("rig", stage.get("backend", "unirig"))
    rigged = backend.run(workdir / "mesh" / "raw.glb", workdir / "rig", stage, gpu)
    subprocess.run(
        [str(HERE / ".venv-bpy" / "bin" / "python"), str(HERE / "inspect_rig.py"), str(rigged),
         str(workdir / "rig" / "bones.json")],
        check=True,
    )
    print("  rig →", rigged)
    return rigged
