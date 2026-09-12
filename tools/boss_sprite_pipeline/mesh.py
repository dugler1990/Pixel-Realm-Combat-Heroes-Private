"""Stage 1: concept cutout(s) → ``mesh/raw.glb`` + Gate A turntable sheet."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .backends import get_backend
from .review import direction_row

HERE = Path(__file__).resolve().parent


def run(cfg: dict, workdir: Path, gpu) -> Path:
    stage = cfg.get("stages", {}).get("mesh", {})
    backend = get_backend("mesh", stage.get("backend", "hunyuan3d"))
    glb = backend.run(workdir / "concept", workdir / "mesh", stage, gpu)
    print("  mesh →", glb)
    turntable(cfg, workdir, glb)
    return glb


def turntable(cfg: dict, workdir: Path, glb: Path) -> Path:
    """Static 8-view render of the mesh (no rig, no actions) for Gate A."""
    tt_dir = workdir / "mesh" / "turntable"
    tt_cfg = {
        "name": cfg["name"], "source": glb.relative_to(workdir).as_posix(),
        "forward_axis": cfg.get("forward_axis", "-Y"), "directions": 8,
        "actions": {"turntable": {"static": True}},
        "camera": cfg.get("camera", {}),
        "render": {**cfg.get("render", {}), "resolution": 256, "samples": 16},
    }
    tt_dir.mkdir(parents=True, exist_ok=True)
    (tt_dir / "render_config.json").write_text(json.dumps(tt_cfg, indent=2), encoding="utf-8")
    subprocess.run(
        [str(HERE / ".venv-bpy" / "bin" / "python"), str(HERE / "render_frames.py"),
         str(tt_dir / "render_config.json"), str(workdir), "--frames-dir", str(tt_dir / "frames")],
        check=True,
    )
    out = direction_row(tt_dir / "frames", "turntable", workdir / "mesh" / "turntable.png")
    print("  Gate A sheet →", out)
    return out
