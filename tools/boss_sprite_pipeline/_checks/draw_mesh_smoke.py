"""Draw one posed mesh-boss frame through the game GPU backend and save a PNG."""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pygame
from OpenGL.GL import GL_RGBA, GL_UNSIGNED_BYTE, glReadPixels

CODE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "Code"))
os.chdir(CODE)
sys.path.insert(0, CODE)

from mesh_boss import MeshBoss  # noqa: E402
from render_backend import create_backend  # noqa: E402


def main():
    out = os.path.abspath(os.path.join(CODE, "..", "logs", "mesh_boss_ingame_smoke.png"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    pygame.init()
    w, h = 1280, 720
    t0 = time.perf_counter()
    backend = create_backend(w, h)
    print("backend", type(backend).__name__, flush=True)
    boss = MeshBoss("demon")
    pos0 = np.asarray(boss.pack.positions[boss.frame_index], dtype=np.float32)
    print("pack", boss.pack.meta["frames"], "frames", boss.pack.meta["tris"], "tris",
          "action", boss.action, "ranges", list(boss.pack.ranges),
          "load_ms", int((time.perf_counter() - t0) * 1000),
          "pos_min", pos0.min(0).tolist(), "pos_max", pos0.max(0).tolist(),
          flush=True)
    if hasattr(backend, "begin_frame"):
        backend.begin_frame((32, 40, 48))
    else:
        backend.fill((32, 40, 48))
    drew = boss.draw(backend, (w * 0.5, h * 0.82), facing_deg=90.0, height_px=650)
    from OpenGL.GL import glFinish
    glFinish()
    pixels = glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)
    backend.present()
    arr = np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 4)
    arr = np.flipud(arr)
    clear = np.array([32, 40, 48], dtype=np.int16)
    painted = int(np.any(np.abs(arr[:, :, :3].astype(np.int16) - clear) > 8, axis=2).sum())
    print("drew", drew, "painted_px", painted, flush=True)
    pygame.image.save(pygame.image.frombytes(arr.tobytes(), (w, h), "RGBA"), out)
    print("wrote", out, flush=True)
    if not drew or painted < 1000:
        raise SystemExit("mesh draw produced no visible pixels")
    pygame.quit()


if __name__ == "__main__":
    main()
