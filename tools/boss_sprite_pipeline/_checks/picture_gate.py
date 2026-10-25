"""Draw baked mesh.npz and skin.npz at one pinned frame and compare silhouettes.

Ambient is 1 so the expected normal difference does not fail the gate. Passes when every
painted pixel of either image sits within 2 px of a painted pixel of the other.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pygame
from OpenGL.GL import GL_RGBA, GL_UNSIGNED_BYTE, glFinish, glReadPixels

CODE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "Code"))
ROOT = os.path.abspath(os.path.join(CODE, ".."))
os.chdir(CODE)
sys.path.insert(0, CODE)

from render_backend import create_backend  # noqa: E402

PACK = os.path.join(ROOT, "Graphics", "Meshes", "demon")
CLEAR = (32, 40, 48)
W, H = 1280, 720


class _Pack:
    skinned = False


def _baked():
    data = np.load(os.path.join(PACK, "mesh.npz"))
    p = _Pack()
    p.name = "demon_baked"
    p.skinned = False
    p.positions = data["positions"]
    p.normals = data["normals"]
    p.uv = data["uv"].astype(np.float32)
    p.indices = data["indices"].astype(np.uint32)
    p.pivot = np.array(data["pivot"], np.float32)
    p.bbox_lo = np.array(data["bbox_lo"], np.float32)
    p.bbox_hi = np.array(data["bbox_hi"], np.float32)
    p.albedo_path = os.path.join(PACK, "albedo.png")
    return p


def _skin():
    data = np.load(os.path.join(PACK, "skin.npz"))
    p = _Pack()
    p.name = "demon_skin"
    p.skinned = True
    p.rest_pos = data["rest_pos"]
    p.rest_nrm = data["rest_nrm"]
    p.uv = data["uv"]
    p.indices = data["indices"]
    p.joints = data["joints"]
    p.weights = data["weights"]
    p.skin_mats = data["skin_mats"]
    p.pivot = np.array(data["pivot"], np.float32)
    p.bbox_lo = np.array(data["bbox_lo"], np.float32)
    p.bbox_hi = np.array(data["bbox_hi"], np.float32)
    p.albedo_path = os.path.join(PACK, "albedo.png")
    return p


def _shot(backend, pack, frame, scale):
    backend.begin_frame(CLEAR)
    ok = backend.draw_mesh_boss(
        pack, frame, (W * 0.5, H * 0.82), 90.0, scale,
        45.0, (-0.4, -0.5, 0.75), 1.0,
    )
    glFinish()
    raw = glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE)
    arr = np.flipud(np.frombuffer(raw, dtype=np.uint8).reshape(H, W, 4))
    clear = np.array(CLEAR, np.int16)
    mask = np.any(np.abs(arr[:, :, :3].astype(np.int16) - clear) > 8, axis=2)
    return ok, mask, arr


def _dilate(mask, radius):
    out = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if max(abs(dx), abs(dy)) > radius:
                continue
            out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    return out


def _within(a, b, radius):
    cover = _dilate(b, radius)
    return int((a & ~cover).sum())


def main():
    frames = [int(a) for a in sys.argv[1:]] or [0]
    pygame.init()
    backend = create_backend(W, H)
    baked, skin = _baked(), _skin()
    height = float(baked.bbox_hi[2] - baked.bbox_lo[2])
    scale = 650.0 / max(height, 1e-6)
    failed = False
    out_dir = os.path.join(ROOT, "logs")
    os.makedirs(out_dir, exist_ok=True)
    for frame in frames:
        ok_b, mb, ab = _shot(backend, baked, frame, scale)
        ok_s, ms, as_ = _shot(backend, skin, frame, scale)
        stray_b = _within(mb, ms, 2)
        stray_s = _within(ms, mb, 2)
        print(
            "[gate] frame", frame, "baked", int(mb.sum()), "skin", int(ms.sum()),
            "stray_baked", stray_b, "stray_skin", stray_s, "drew", ok_b, ok_s,
            flush=True,
        )
        if stray_b or stray_s or not ok_b or not ok_s or mb.sum() < 1000:
            failed = True
            pygame.image.save(
                pygame.image.frombytes(ab.tobytes(), (W, H), "RGBA"),
                os.path.join(out_dir, "gate_baked_%d.png" % frame),
            )
            pygame.image.save(
                pygame.image.frombytes(as_.tobytes(), (W, H), "RGBA"),
                os.path.join(out_dir, "gate_skin_%d.png" % frame),
            )
    pygame.quit()
    if failed:
        raise SystemExit("picture gate failed")
    print("[gate] pass", flush=True)


if __name__ == "__main__":
    main()
