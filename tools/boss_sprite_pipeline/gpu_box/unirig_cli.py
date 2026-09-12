"""UniRig wrapper: GLB → rigged GLB (skeleton + skin weights). Runs in gpu_box/vendor/unirig/.venv.

    unirig_cli.py --mesh raw.glb --out rigged.glb [--seed 0]

Drives UniRig's three launch scripts (skeleton → skin → merge) from its own
checkout, as the upstream README documents. Not yet exercised on the box.
"""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

VENDOR = Path(__file__).resolve().parent / "vendor" / "unirig"


def sh(script: str, *args: str) -> None:
    cmd = ["bash", str(VENDOR / "launch" / "inference" / script), *args]
    print("  $", " ".join(cmd), flush=True)
    env = dict(os.environ, PATH=f"{VENDOR / '.venv' / 'bin'}:{os.environ['PATH']}")
    subprocess.run(cmd, cwd=VENDOR, check=True, env=env)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mesh", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    mesh = Path(args.mesh).resolve()
    out = Path(args.out).resolve()
    work = out.parent / "unirig_work"
    work.mkdir(parents=True, exist_ok=True)
    skeleton = work / "skeleton.fbx"
    skinned = work / "skin.fbx"

    sh("generate_skeleton.sh", "--input", str(mesh), "--output", str(skeleton), "--seed", str(args.seed))
    sh("generate_skin.sh", "--input", str(skeleton), "--output", str(skinned))
    sh("merge.sh", "--source", str(skinned), "--target", str(mesh), "--output", str(out))
    print("wrote", out)


if __name__ == "__main__":
    main()
