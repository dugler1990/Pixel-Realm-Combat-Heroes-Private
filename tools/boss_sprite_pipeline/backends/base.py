"""Backend interfaces for the ML stages (mesh, rig).

A backend turns files into files. It never knows which machine it is on: it
asks ``GpuExec`` to run a ``gpu_box/*_cli.py`` wrapper, and GpuExec decides
whether that is a local subprocess or ssh+rsync to ``gpu_host``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .gpu_exec import GpuExec

REGISTRY: dict[str, dict[str, type]] = {"mesh": {}, "rig": {}}


def register(kind: str, name: str) -> Callable[[type], type]:
    def deco(cls: type) -> type:
        cls.name = name
        REGISTRY[kind][name] = cls
        return cls
    return deco


def get_backend(kind: str, name: str):
    try:
        return REGISTRY[kind][name]()
    except KeyError:
        raise SystemExit(f"unknown {kind} backend {name!r}; known: {sorted(REGISTRY[kind])}") from None


class MeshBackend:
    """concept images → textured GLB."""
    name = "?"

    def run(self, concept_dir: Path, mesh_dir: Path, cfg: dict, gpu: GpuExec) -> Path:
        raise NotImplementedError


class RigBackend:
    """GLB → rigged GLB (skeleton + skin weights)."""
    name = "?"

    def run(self, mesh_glb: Path, rig_dir: Path, cfg: dict, gpu: GpuExec) -> Path:
        raise NotImplementedError
