"""TRELLIS wrapper: image → textured GLB. Runs in gpu_box/vendor/trellis/.venv.

    trellis_cli.py --image front.png --out mesh.glb [--seed 0] [--max-faces 40000]

Written against the upstream README (TrellisImageTo3DPipeline + postprocessing_utils);
not yet exercised on the box.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-faces", type=int, default=40000)
    args = ap.parse_args()

    os.environ.setdefault("SPCONV_ALGO", "native")
    from PIL import Image
    from trellis.pipelines import TrellisImageTo3DPipeline
    from trellis.utils import postprocessing_utils

    pipe = TrellisImageTo3DPipeline.from_pretrained("microsoft/TRELLIS-image-large")
    pipe.cuda()
    outputs = pipe.run(Image.open(args.image), seed=args.seed)
    glb = postprocessing_utils.to_glb(
        outputs["gaussian"][0], outputs["mesh"][0],
        simplify=0.95, texture_size=1024,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    glb.export(str(out))
    print("wrote", out)


if __name__ == "__main__":
    main()
