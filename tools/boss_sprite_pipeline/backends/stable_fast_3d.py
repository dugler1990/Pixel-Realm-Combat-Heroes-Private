"""Stable Fast 3D (Stability AI) - image to textured GLB on the GPU box."""
from __future__ import annotations

from pathlib import Path

from .base import MeshBackend, register


@register("mesh", "stable_fast_3d")
class StableFast3D(MeshBackend):
    def run(self, concept_dir: Path, mesh_dir: Path, cfg: dict, gpu) -> Path:
        mesh_dir.mkdir(parents=True, exist_ok=True)
        out = mesh_dir / "raw.glb"
        front = concept_dir / "front.png"
        if not front.exists():
            raise SystemExit(f"stable_fast_3d: {front} missing (run the concept stage)")
        args = [
            "--image", gpu.rel(front),
            "--out", gpu.rel(out),
            "--texture-resolution", str(cfg.get("texture_resolution", 1024)),
            "--foreground-ratio", str(cfg.get("foreground_ratio", 0.85)),
        ]
        gpu.run("stable_fast_3d", args, inputs=[front], outputs=[out])
        return out
