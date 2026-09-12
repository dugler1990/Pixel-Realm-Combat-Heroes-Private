"""Hunyuan3D-2 wrapper: concept view(s) → textured GLB. Runs in gpu_box/vendor/hunyuan3d/.venv.

    hunyuan3d_cli.py --view front=path.png [--view back=... --view left=... --view right=...]
                     --out mesh.glb [--texture] [--variant tencent/Hunyuan3D-2|tencent/Hunyuan3D-2mini|tencent/Hunyuan3D-2mv]
                     [--steps 30] [--octree 256] [--seed 0] [--max-faces 40000]

Written against the upstream README API (hy3dgen.shapegen / hy3dgen.texgen);
not yet exercised on the box — see gpu_box/setup.sh.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--view", action="append", required=True, help="name=path (front|back|left|right)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--variant", default="tencent/Hunyuan3D-2")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--octree", type=int, default=256)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--texture", action="store_true")
    ap.add_argument("--max-faces", type=int, default=40000)
    args = ap.parse_args()

    import torch
    from PIL import Image
    from hy3dgen.rembg import BackgroundRemover
    from hy3dgen.shapegen import (DegenerateFaceRemover, FaceReducer, FloaterRemover,
                                  Hunyuan3DDiTFlowMatchingPipeline)

    views = {}
    for spec in args.view:
        name, path = spec.split("=", 1)
        img = Image.open(path).convert("RGBA")
        if img.getextrema()[3][0] == 255:  # no transparency → strip background
            img = BackgroundRemover()(img.convert("RGB"))
        views[name] = img

    multiview = len(views) > 1 or "2mv" in args.variant
    kwargs = {}
    if "2mini" in args.variant:
        kwargs = {"subfolder": "hunyuan3d-dit-v2-mini", "variant": "fp16"}
    elif multiview:
        kwargs = {"subfolder": "hunyuan3d-dit-v2-mv", "variant": "fp16"}
        args.variant = "tencent/Hunyuan3D-2mv"
    pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(args.variant, **kwargs)
    image_arg = views if multiview else views["front"]
    mesh = pipe(
        image=image_arg,
        num_inference_steps=args.steps,
        octree_resolution=args.octree,
        generator=torch.manual_seed(args.seed),
    )[0]
    mesh = FloaterRemover()(mesh)
    mesh = DegenerateFaceRemover()(mesh)
    mesh = FaceReducer()(mesh, max_facenum=args.max_faces)

    if args.texture:
        from hy3dgen.texgen import Hunyuan3DPaintPipeline
        paint = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2")
        mesh = paint(mesh, image=views["front"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(str(out))
    print("wrote", out, "faces", len(mesh.faces))


if __name__ == "__main__":
    main()
