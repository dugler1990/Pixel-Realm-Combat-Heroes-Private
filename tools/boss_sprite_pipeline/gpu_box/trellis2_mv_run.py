#!/usr/bin/env python3
"""TRELLIS.2 from several views of one figure (trellis2_multiview.py), exported exactly as trellis2_run.py does.

    /workspace/vendor/trellis2-venv/bin/python -u /workspace/gpu_box/trellis2_mv_run.py \
      --front /workspace/in/<front>.png --back /workspace/in/<back>.png [--right ...] [--left ...] \
      [--front_left ...] [--front_right ...] [--back_left ...] [--back_right ...] \
      --out-dir /workspace/out --name <stem> [--band 0.03]

Images: real-alpha cutouts, same figure, same pose and framing; back = seen from behind (his left on the image's
left). Writes <stem>_from_front.glb (+ _raw_extract.pt) like trellis2_run.py --skip-texture.
"""
import argparse
from pathlib import Path

import trellis2_run as base                       # applies the patches, chdir + sys.path to TRELLIS.2, export helpers
import torch
from PIL import Image
from trellis2.pipelines import Trellis2ImageTo3DPipeline
from trellis2_multiview import VIEWS, run_multiview


def main():
    ap = argparse.ArgumentParser()
    for v in VIEWS:                    # front back right left front_left front_right back_left back_right
        ap.add_argument(f"--{v}", required=v == "front")
    ap.add_argument("--out-dir", default="/workspace/out")
    ap.add_argument("--name", required=True)
    ap.add_argument("--band", type=float, default=0.03)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    images = {v: Image.open(getattr(a, v)).convert("RGBA") for v in VIEWS if getattr(a, v)}
    for v, im in images.items():
        print("IMAGE", v, getattr(a, v), im.size, flush=True)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    print("LOAD_I23D", flush=True)
    pipe = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
    pipe.cuda()
    print(f"RUN multiview views={list(images)} band={a.band} seed={a.seed} pipeline_type=1024_cascade", flush=True)
    mesh = run_multiview(pipe, images, seed=a.seed, band=a.band)
    base._log_mem("after_generate")
    print("GENERATE verts", len(mesh.vertices), "faces", len(mesh.faces), flush=True)
    base.save_extract(mesh, out / f"{a.name}_raw_extract.pt")
    del pipe
    torch.cuda.empty_cache()
    base.export_isolated_remesh(mesh, out / f"{a.name}_from_front.glb")
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    main()
