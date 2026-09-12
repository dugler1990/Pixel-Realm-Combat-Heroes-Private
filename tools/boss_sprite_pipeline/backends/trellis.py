"""TRELLIS (Microsoft, open weights) — image → textured GLB on the GPU box."""
from __future__ import annotations

from pathlib import Path

from .base import MeshBackend, register


@register("mesh", "trellis")
class Trellis(MeshBackend):
    def run(self, concept_dir: Path, mesh_dir: Path, cfg: dict, gpu) -> Path:
        mesh_dir.mkdir(parents=True, exist_ok=True)
        out = mesh_dir / "raw.glb"
        front = concept_dir / "front.png"
        if not front.exists():
            raise SystemExit(f"trellis: {front} missing (run the concept stage)")
        args = ["--image", gpu.rel(front), "--out", gpu.rel(out), "--seed", str(cfg.get("seed", 0))]
        if cfg.get("max_faces"):
            args += ["--max-faces", str(cfg["max_faces"])]
        gpu.run("trellis", args, inputs=[front], outputs=[out])
        return out
