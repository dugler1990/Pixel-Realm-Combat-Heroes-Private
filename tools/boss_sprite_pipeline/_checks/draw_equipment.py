"""Draw a mesh player with worn pieces through the game's GPU backend (player_mesh.PlayerMesh.draw) and save a PNG.

    Code/sprite_venv/Scripts/python.exe tools/boss_sprite_pipeline/_checks/draw_equipment.py <out.png>
        [--body barb] [--pieces barb_fullplate/chest,...|all|none] [--px 260]

Rows: idle (first frame), move (middle), attack (middle). Columns: facing down, down-left, left, up (screen
headings 90, 135, 180, 270). Same body pivot / scale / frame for every piece, one depth clear per figure.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

import numpy as np
import pygame

CODE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "Code"))
os.chdir(CODE)
sys.path.insert(0, CODE)

from OpenGL.GL import GL_RGBA, GL_UNSIGNED_BYTE, glFinish, glReadPixels  # noqa: E402

from player_mesh import PlayerMesh  # noqa: E402
from render_backend import create_backend  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--body", default="barb")
    ap.add_argument("--pieces", default="all")
    ap.add_argument("--px", type=int, default=260)
    a = ap.parse_args()
    if a.pieces == "all":
        pieces = sorted(os.path.relpath(p, "../Graphics/Meshes").replace("\\", "/")
                        for p in glob.glob("../Graphics/Meshes/barb_fullplate/*") if os.path.isdir(p))
    elif a.pieces == "none":
        pieces = []
    else:
        pieces = a.pieces.split(",")
    pygame.init()
    headings, clips = (90.0, 135.0, 180.0, 270.0), ("idle", "move", "attack")
    cw, ch = int(a.px * 1.1), int(a.px * 1.35)
    w, h = cw * len(headings), ch * len(clips)
    backend = create_backend(w, h)
    m = PlayerMesh(a.body, a.px)
    m.set_pieces(pieces)
    print("pieces", list(m.pieces), flush=True)
    backend.begin_frame((40, 44, 52)) if hasattr(backend, "begin_frame") else backend.fill((40, 44, 52))
    for r, clip in enumerate(clips):
        m.skin.set_action(clip)
        lo, hi = m.skin.pack.ranges[m.skin.action]
        m.skin.frame = 0.0 if clip == "idle" else float((hi - lo) // 2)
        for c, heading in enumerate(headings):
            m.facing_deg = heading
            ok = m.draw(backend, (c * cw + cw * 0.5, r * ch + ch * 0.9))
            if not ok:
                raise SystemExit("the backend drew nothing (CPU backend?)")
    glFinish()
    arr = np.flipud(np.frombuffer(glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE), np.uint8).reshape(h, w, 4))
    pygame.image.save(pygame.image.frombytes(arr.tobytes(), (w, h), "RGBA"), a.out)
    backend.present()
    print("wrote", a.out, flush=True)
    pygame.quit()


if __name__ == "__main__":
    main()
