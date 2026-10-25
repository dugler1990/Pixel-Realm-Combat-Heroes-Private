"""GPU coverage check: capsule mask vs depth silhouette.

Draws the demon across frames and 8 facings, reads the depth silhouette, and
prints how much of the silhouette the capsules miss and how much of the capsule
mask is empty space. Run after every bake. Not part of the headless suite.

    python -m tools.boss_sprite_pipeline.check_body_capsules demon
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import numpy as np

# Engine assets are resolved relative to Code/.
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
CODE_DIR = os.path.join(REPO_ROOT, "Code")
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)
os.chdir(CODE_DIR)

os.environ.setdefault("SDL_VIDEODRIVER", "windows" if os.name == "nt" else "x11")

import pygame  # noqa: E402
from OpenGL.GL import (  # noqa: E402
    GL_DEPTH_COMPONENT,
    GL_FLOAT,
    glReadPixels,
)

from mesh_boss import MeshBoss, build_body_mask, project_model_points  # noqa: E402
from render_backend import GPUBackend, create_backend  # noqa: E402
from Settings import RENDER_BACKEND  # noqa: E402


FACINGS = (0, 45, 90, 135, 180, 225, 270, 315)


def _depth_mask(backend, x0, y0, w, h):
    if w <= 0 or h <= 0:
        return None
    gl_y = backend._height - (y0 + h)
    raw = glReadPixels(x0, gl_y, w, h, GL_DEPTH_COMPONENT, GL_FLOAT)
    if isinstance(raw, np.ndarray):
        depth = np.array(raw, dtype=np.float32, copy=True)
    else:
        depth = np.frombuffer(raw, dtype=np.float32).copy()
    if depth.size != w * h:
        return None
    depth = np.flipud(depth.reshape(h, w))
    return depth < 1.0


def _mask_to_bool(mask):
    w, h = mask.get_size()
    arr = np.zeros((h, w), dtype=bool)
    for y in range(h):
        for x in range(w):
            if mask.get_at((x, y)):
                arr[y, x] = True
    return arr


def check_pack(name: str, frames: int, height_px: float) -> int:
    if RENDER_BACKEND != "gpu":
        print("RENDER_BACKEND is not gpu; refusing to run coverage check")
        return 2
    width, height = 1280, 720
    pygame.init()
    backend = create_backend(width, height)
    if not isinstance(backend, GPUBackend):
        print("create_backend did not return GPUBackend")
        return 2

    boss = MeshBoss(name)
    pack = boss.pack
    scale = height_px / max(pack.height_units, 1e-6)
    screen_pos = (width // 2, int(height * 0.85))

    lo, hi = pack.ranges.get("settle_01", next(iter(pack.ranges.values())))
    frame_ids = np.linspace(lo, hi, num=max(1, frames), dtype=int)

    miss_total = 0
    sil_total = 0
    empty_total = 0
    cap_total = 0
    samples = 0

    for frame in frame_ids:
        for facing in FACINGS:
            backend.begin_frame()
            backend.clear((20, 20, 24))
            # Depth clear for the whole window.
            from OpenGL.GL import glClear, GL_DEPTH_BUFFER_BIT, glEnable, GL_DEPTH_TEST
            glEnable(GL_DEPTH_TEST)
            glClear(GL_DEPTH_BUFFER_BIT)
            backend.draw_mesh_boss(
                pack, int(frame), screen_pos, float(facing), scale,
                45.0, (-0.4, -0.5, 0.75), 0.35,
            )
            x0, y0, x1, y1, clipped = backend._mesh_projected_bounds(
                pack, screen_pos, facing, scale, 45.0)
            if clipped:
                backend.end_frame()
                continue
            w, h = x1 - x0, y1 - y0
            covered = _depth_mask(backend, x0, y0, w, h)
            backend.end_frame()
            if covered is None:
                continue

            cap_mask, dx, dy = build_body_mask(pack, int(frame), float(facing), scale, 45.0)
            # Place capsule mask into the same window box as the depth read.
            cap_x = int(round(screen_pos[0] + dx)) - x0
            cap_y = int(round(screen_pos[1] + dy)) - y0
            cw, ch = cap_mask.get_size()
            cap = np.zeros((h, w), dtype=bool)
            for y in range(ch):
                yy = cap_y + y
                if yy < 0 or yy >= h:
                    continue
                for x in range(cw):
                    xx = cap_x + x
                    if xx < 0 or xx >= w:
                        continue
                    if cap_mask.get_at((x, y)):
                        cap[yy, xx] = True

            sil = int(covered.sum())
            cap_n = int(cap.sum())
            miss = int((covered & ~cap).sum())
            empty = int((cap & ~covered).sum())
            sil_total += sil
            cap_total += cap_n
            miss_total += miss
            empty_total += empty
            samples += 1

    if samples == 0:
        print("no samples (everything clipped?)")
        return 1
    miss_frac = miss_total / max(1, sil_total)
    empty_frac = empty_total / max(1, cap_total)
    print(
        f"[check-body] pack={name} samples={samples} "
        f"silhouette_miss={miss_frac:.3%} "
        f"capsule_empty={empty_frac:.3%}"
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", default="demon", nargs="?", help="mesh pack name")
    parser.add_argument("--frames", type=int, default=5, help="frames sampled per clip")
    parser.add_argument("--height", type=float, default=850.0, help="draw height in px")
    args = parser.parse_args(argv)
    return check_pack(args.name, args.frames, args.height)


if __name__ == "__main__":
    sys.exit(main())
