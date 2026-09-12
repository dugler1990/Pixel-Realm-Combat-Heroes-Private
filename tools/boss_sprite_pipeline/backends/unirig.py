"""UniRig (VAST/Tsinghua, open weights) — arbitrary mesh → skeleton + skin weights."""
from __future__ import annotations

from pathlib import Path

from .base import RigBackend, register


@register("rig", "unirig")
class UniRig(RigBackend):
    def run(self, mesh_glb: Path, rig_dir: Path, cfg: dict, gpu) -> Path:
        rig_dir.mkdir(parents=True, exist_ok=True)
        out = rig_dir / "rigged.glb"
        args = ["--mesh", gpu.rel(mesh_glb), "--out", gpu.rel(out), "--seed", str(cfg.get("seed", 0))]
        gpu.run("unirig", args, inputs=[mesh_glb], outputs=[out])
        return out
