"""Stable Fast 3D wrapper: one RGBA concept image to a textured GLB."""
from __future__ import annotations

import argparse
import sys
from contextlib import nullcontext
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--texture-resolution", type=int, default=1024)
    ap.add_argument("--foreground-ratio", type=float, default=0.85)
    args = ap.parse_args()

    vendor = Path(__file__).resolve().parent / "vendor" / "stable_fast_3d"
    sys.path.insert(0, str(vendor))

    import torch
    from PIL import Image
    from sf3d.system import SF3D
    from sf3d.utils import resize_foreground

    if not torch.cuda.is_available():
        raise SystemExit("Stable Fast 3D cloud wrapper requires a CUDA GPU")
    print("CUDA:", torch.cuda.get_device_name(0), "torch", torch.__version__)

    image = resize_foreground(Image.open(args.image).convert("RGBA"), args.foreground_ratio)
    model = SF3D.from_pretrained(
        "stabilityai/stable-fast-3d",
        config_name="config.yaml",
        weight_name="model.safetensors",
    )
    model.to("cuda")
    model.eval()

    torch.cuda.reset_peak_memory_stats()
    with torch.no_grad():
        autocast = (
            torch.autocast(device_type="cuda", dtype=torch.bfloat16)
            if torch.cuda.is_bf16_supported()
            else nullcontext()
        )
        with autocast:
            mesh, _ = model.run_image(
                [image],
                bake_resolution=args.texture_resolution,
                remesh="none",
                vertex_count=-1,
            )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(out), include_normals=True)
    peak_mb = torch.cuda.max_memory_allocated() / 1024 / 1024
    print("wrote", out, "peak VRAM MiB", round(peak_mb))


if __name__ == "__main__":
    main()
