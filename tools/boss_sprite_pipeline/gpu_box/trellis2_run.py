#!/usr/bin/env python3
"""TRELLIS.2 image-to-3D (remesh=True) then PBR retexture from the same still.

    /workspace/vendor/trellis2-venv/bin/python -u \
      /workspace/gpu_box/trellis2_run.py \
      --image /workspace/in/front.png \
      --out-dir /workspace/out \
      --name demon
"""
from __future__ import annotations

import argparse
import faulthandler
import os
import sys
from pathlib import Path

faulthandler.enable(all_threads=True)
os.environ.setdefault("PYTHONFAULTHANDLER", "1")

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
os.environ.setdefault("CUDA_HOME", "/usr/local/cuda")
os.environ.setdefault("ATTN_BACKEND", "sdpa")
os.environ.setdefault("SPARSE_ATTN_BACKEND", "flash_attn")
os.environ.setdefault("HF_HOME", "/workspace/.cache/huggingface")

import torch
import trimesh
from PIL import Image

ROOT = Path("/workspace/vendor/TRELLIS.2")
GPU_BOX = Path("/workspace/gpu_box")
sys.path.insert(0, str(GPU_BOX))
from trellis2_patch import main as apply_patches

apply_patches()

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import o_voxel  # noqa: E402
from trellis2.pipelines import Trellis2ImageTo3DPipeline, Trellis2TexturingPipeline  # noqa: E402


def _rss_mb() -> float:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0
    except OSError:
        return -1.0
    return -1.0


def _log_mem(tag: str) -> None:
    gpu = -1.0
    reserved = -1.0
    if torch.cuda.is_available():
        gpu = torch.cuda.memory_allocated() / 1024**2
        reserved = torch.cuda.memory_reserved() / 1024**2
    print(
        f"MEM {tag} rss_mb={_rss_mb():.0f} cuda_alloc_mb={gpu:.0f} cuda_reserved_mb={reserved:.0f}",
        flush=True,
    )


def _as_cuda_tensor(x, dtype):
    if torch.is_tensor(x):
        return x.to(device="cuda", dtype=dtype)
    return torch.as_tensor(x, dtype=dtype, device="cuda")


def save_extract(mesh, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "vertices": mesh.vertices.detach().cpu() if torch.is_tensor(mesh.vertices) else mesh.vertices,
            "faces": mesh.faces.detach().cpu() if torch.is_tensor(mesh.faces) else mesh.faces,
            "voxel_size": mesh.voxel_size.detach().cpu() if torch.is_tensor(mesh.voxel_size) else mesh.voxel_size,
            "attrs": mesh.attrs.detach().cpu() if torch.is_tensor(mesh.attrs) else mesh.attrs,
            "coords": mesh.coords.detach().cpu() if torch.is_tensor(mesh.coords) else mesh.coords,
        },
        path,
    )
    print("WROTE_EXTRACT", path, "bytes", path.stat().st_size, flush=True)


def export_isolated_remesh(mesh, out: Path) -> None:
    """Official 1024 remesh (band=1, project=0) without UV unwrap / texture bake."""
    import cumesh

    vertices = _as_cuda_tensor(mesh.vertices, torch.float32)
    faces = _as_cuda_tensor(mesh.faces, torch.int32)
    aabb = torch.tensor([[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]], device="cuda", dtype=torch.float32)
    voxel_size = _as_cuda_tensor(mesh.voxel_size, torch.float32)
    if voxel_size.numel() == 1:
        voxel_size = voxel_size.repeat(3)
    grid_size = ((aabb[1] - aabb[0]) / voxel_size).round().int()
    remesh_band = 1.0
    remesh_project = 0.0
    resolution = int(grid_size.max().item())
    center = aabb.mean(dim=0)
    scale = (aabb[1] - aabb[0]).max().item()
    scale = (resolution + 3 * remesh_band) / resolution * scale
    print(
        "ISOLATED_REMESH verts",
        int(vertices.shape[0]),
        "faces",
        int(faces.shape[0]),
        "grid",
        grid_size.tolist(),
        "resolution",
        resolution,
        flush=True,
    )
    _log_mem("before_fill_holes")
    cu = cumesh.CuMesh()
    cu.init(vertices, faces)
    cu.fill_holes(max_hole_perimeter=3e-2)
    vertices, faces = cu.read()
    print("After filling holes:", int(vertices.shape[0]), "verts", int(faces.shape[0]), "faces", flush=True)
    print("Building BVH...", flush=True)
    bvh = cumesh.cuBVH(vertices, faces)
    torch.cuda.synchronize()
    print("BVH ok", flush=True)
    _log_mem("after_bvh")
    print("BEGIN remesh_narrow_band_dc", flush=True)
    new_v, new_f = cumesh.remeshing.remesh_narrow_band_dc(
        vertices,
        faces,
        center=center,
        scale=scale,
        resolution=resolution,
        band=remesh_band,
        project_back=remesh_project,
        verbose=True,
        bvh=bvh,
    )
    torch.cuda.synchronize()
    print("REMESH ok verts", int(new_v.shape[0]), "faces", int(new_f.shape[0]), flush=True)
    _log_mem("after_remesh")
    cu.init(new_v, new_f)
    cu.simplify(1_000_000, verbose=True)
    new_v, new_f = cu.read()
    print("After simplify verts", int(new_v.shape[0]), "faces", int(new_f.shape[0]), flush=True)
    print("BAKE to_glb remesh=False from generate PBR attrs", flush=True)
    glb = o_voxel.postprocess.to_glb(
        vertices=new_v,
        faces=new_f,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=1_000_000,
        texture_size=2048,
        remesh=False,
        remesh_band=1,
        remesh_project=0,
        verbose=True,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    glb.export(str(out), extension_webp=False)
    _log_mem("after_export")
    print("WROTE", out, "bytes", out.stat().st_size, flush=True)


def export_generated(mesh, out: Path, *, remesh: bool) -> None:
    print(
        "EXPORT start remesh",
        remesh,
        "verts",
        len(mesh.vertices),
        "faces",
        len(mesh.faces),
        flush=True,
    )
    _log_mem(f"before_simplify remesh={remesh}")
    mesh.simplify(16777216)
    print("EXPORT after_simplify verts", len(mesh.vertices), "faces", len(mesh.faces), flush=True)
    _log_mem(f"before_to_glb remesh={remesh}")
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=1_000_000,
        texture_size=2048,
        remesh=remesh,
        remesh_band=1,
        remesh_project=0,
        verbose=True,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    glb.export(str(out), extension_webp=False)
    _log_mem(f"after_export remesh={remesh}")
    print("WROTE", out, "bytes", out.stat().st_size, "remesh", remesh, flush=True)


def generate_mesh(pipeline, image: Image.Image):
    try:
        print("RUN pipeline_type=1024_cascade", flush=True)
        return pipeline.run(image, seed=0, pipeline_type="1024_cascade")[0]
    except torch.cuda.OutOfMemoryError:
        print("OOM 1024_cascade, retry 512", flush=True)
        torch.cuda.empty_cache()
        return pipeline.run(image, seed=0, pipeline_type="512")[0]


def load_mesh(path: Path):
    mesh = trimesh.load(str(path))
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.to_mesh()
    return mesh


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default="/workspace/in/front.png")
    ap.add_argument("--out-dir", default="/workspace/out")
    ap.add_argument("--name", default="demon")
    ap.add_argument("--skip-generate", action="store_true")
    ap.add_argument("--skip-texture", action="store_true")
    ap.add_argument("--no-remesh", action="store_true", help="debug only; default remesh=True")
    args = ap.parse_args()

    image_path = Path(args.image)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = out_dir / f"{args.name}_from_front.glb"
    painted = out_dir / f"{args.name}_painted.glb"
    image = Image.open(image_path).convert("RGBA")
    print("IMAGE", image_path, image.size, image.mode, flush=True)
    remesh = not args.no_remesh
    print("REMESH", remesh, flush=True)

    if not args.skip_generate:
        print("LOAD_I23D", flush=True)
        i23d = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
        i23d.cuda()
        mesh = generate_mesh(i23d, image)
        _log_mem("after_generate")
        print("GENERATE verts", len(mesh.vertices), "faces", len(mesh.faces), flush=True)
        save_extract(mesh, out_dir / f"{args.name}_raw_extract.pt")
        del i23d
        torch.cuda.empty_cache()
        _log_mem("after_free_pipeline")
        if remesh:
            print("BEGIN isolated remesh=True (no UV bake)", flush=True)
            export_isolated_remesh(mesh, raw)
        else:
            print("SKIP remesh, to_glb remesh=False", flush=True)
            export_generated(mesh, raw, remesh=False)
        del mesh
        torch.cuda.empty_cache()
        _log_mem("after_generate_export")
    elif not raw.exists():
        raise SystemExit(f"missing {raw} (generate first)")

    if not args.skip_texture:
        print("LOAD_TEX", flush=True)
        tex = Trellis2TexturingPipeline.from_pretrained(
            "microsoft/TRELLIS.2-4B", config_file="texturing_pipeline.json"
        )
        tex.cuda()
        print("RUN_TEX", raw, flush=True)
        output = tex.run(load_mesh(raw), image, seed=0)
        output.export(str(painted), extension_webp=False)
        print("WROTE", painted, "bytes", painted.stat().st_size, flush=True)

    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    main()
