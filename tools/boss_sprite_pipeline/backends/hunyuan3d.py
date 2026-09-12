"""Hunyuan3D-2 (Tencent, open weights) — image(s) → textured GLB on the GPU box."""
from __future__ import annotations

from pathlib import Path

from .base import MeshBackend, register

VIEW_FILES = {"front": "front.png", "back": "back.png", "left": "left.png", "right": "right.png"}


@register("mesh", "hunyuan3d")
class Hunyuan3D(MeshBackend):
    def run(self, concept_dir: Path, mesh_dir: Path, cfg: dict, gpu) -> Path:
        mesh_dir.mkdir(parents=True, exist_ok=True)
        out = mesh_dir / "raw.glb"
        views = {v: concept_dir / f for v, f in VIEW_FILES.items() if (concept_dir / f).exists()}
        if "front" not in views:
            raise SystemExit(f"hunyuan3d: {concept_dir / 'front.png'} missing (run the concept stage)")
        args = ["--out", gpu.rel(out)]
        for view, path in views.items():
            args += ["--view", f"{view}={gpu.rel(path)}"]
        args += ["--variant", cfg.get("variant", "tencent/Hunyuan3D-2")]
        args += ["--steps", str(cfg.get("steps", 30)), "--octree", str(cfg.get("octree_resolution", 256))]
        args += ["--seed", str(cfg.get("seed", 0))]
        if cfg.get("texture", True):
            args.append("--texture")
        if cfg.get("max_faces"):
            args += ["--max-faces", str(cfg["max_faces"])]
        gpu.run("hunyuan3d", args, inputs=list(views.values()), outputs=[out])
        return out
