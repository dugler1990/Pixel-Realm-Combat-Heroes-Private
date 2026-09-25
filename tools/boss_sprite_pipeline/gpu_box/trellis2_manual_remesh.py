#!/usr/bin/env python3
"""Isolated CuMesh remesh of an existing GLB. No generate, no UV unwrap, no texture bake."""
from __future__ import annotations

import argparse
import faulthandler
import os
import sys
from pathlib import Path

faulthandler.enable(all_threads=True)
os.environ["CUDA_LAUNCH_BLOCKING"] = "1"
os.environ.setdefault("CUDA_HOME", "/usr/local/cuda")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch
import trimesh
import cumesh


def _rss_mb() -> float:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except OSError:
        return -1.0
    return -1.0


def _log_mem(tag: str) -> None:
    gpu = reserved = -1.0
    if torch.cuda.is_available():
        gpu = torch.cuda.memory_allocated() / 1024**2
        reserved = torch.cuda.memory_reserved() / 1024**2
    print(
        f"MEM {tag} rss_mb={_rss_mb():.0f} cuda_alloc_mb={gpu:.0f} cuda_reserved_mb={reserved:.0f}",
        flush=True,
    )


def load_mesh(path: Path) -> trimesh.Trimesh:
    mesh = trimesh.load(str(path), force="mesh")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_mesh()
    return mesh


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="/workspace/out/demon_from_front_noremesh.glb")
    ap.add_argument("--out", default="/workspace/out/demon_from_front_manual_remesh.glb")
    ap.add_argument("--resolution", type=int, default=1024)
    ap.add_argument("--band", type=float, default=1.0)
    ap.add_argument("--project-back", type=float, default=0.0)
    args = ap.parse_args()

    inp = Path(args.inp)
    out = Path(args.out)
    print("GPU", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none", flush=True)
    print("CUMESH", getattr(cumesh, "__file__", None), flush=True)
    print("IN", inp, "exists", inp.exists(), flush=True)
    if not inp.exists():
        raise SystemExit(f"missing {inp}")

    mesh = load_mesh(inp)
    print("LOAD verts", len(mesh.vertices), "faces", len(mesh.faces), flush=True)
    verts = torch.from_numpy(mesh.vertices).float().cuda()
    faces = torch.from_numpy(mesh.faces).int().cuda()
    aabb_min = verts.min(dim=0).values
    aabb_max = verts.max(dim=0).values
    center = (aabb_min + aabb_max) * 0.5
    scale = (aabb_max - aabb_min).max().item()
    print("AABB center", center.tolist(), "scale", scale, "res", args.resolution, flush=True)
    _log_mem("before_bvh")

    print("Building BVH...", flush=True)
    bvh = cumesh.cuBVH(verts, faces)
    torch.cuda.synchronize()
    print("BVH ok", flush=True)
    _log_mem("after_bvh")

    print("BEGIN remesh_narrow_band_dc", flush=True)
    new_v, new_f = cumesh.remeshing.remesh_narrow_band_dc(
        verts,
        faces,
        center=center,
        scale=scale,
        resolution=args.resolution,
        band=args.band,
        project_back=args.project_back,
        verbose=True,
        bvh=bvh,
    )
    torch.cuda.synchronize()
    print("REMESH ok verts", int(new_v.shape[0]), "faces", int(new_f.shape[0]), flush=True)
    _log_mem("after_remesh")

    out.parent.mkdir(parents=True, exist_ok=True)
    trimesh.Trimesh(
        vertices=new_v.detach().cpu().numpy(),
        faces=new_f.detach().cpu().numpy(),
        process=False,
    ).export(str(out))
    print("WROTE", out, "bytes", out.stat().st_size, flush=True)
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.excepthook(*sys.exc_info())
        torch.cuda.synchronize()
        raise
