"""Pass-through backends: the stage's output is supplied by hand.

``mesh: none`` expects ``mesh/raw.glb`` to already exist (e.g. a hand-made or
downloaded model). ``rig: none`` copies the mesh through unrigged — the boss is
a static turntable and every motion comes from stage 3's procedural layer.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .base import MeshBackend, RigBackend, register


@register("mesh", "none")
class NoneMesh(MeshBackend):
    def run(self, concept_dir: Path, mesh_dir: Path, cfg: dict, gpu) -> Path:
        out = mesh_dir / "raw.glb"
        if not out.exists():
            raise SystemExit(f"mesh backend 'none': put a model at {out} first")
        return out


@register("rig", "none")
class NoneRig(RigBackend):
    def run(self, mesh_glb: Path, rig_dir: Path, cfg: dict, gpu) -> Path:
        out = rig_dir / "rigged.glb"
        rig_dir.mkdir(parents=True, exist_ok=True)
        if mesh_glb.resolve() != out.resolve():
            shutil.copyfile(mesh_glb, out)
        return out
