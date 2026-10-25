"""Normalize Meteor/descent frames so the rocky ball is a consistent size.

Backs up originals once, always re-reads from backup (idempotent), detects the
ball as the thickest opaque mass near the leading tip, scales to a shared ball
radius, and plants every frame on one canvas with ball centers aligned.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DESCENT = ROOT / "Graphics" / "Particles" / "Meteor" / "descent"
BACKUP = ROOT / "Graphics" / "Particles" / "Meteor" / "_originals" / "descent"
DEBUG = ROOT / "Graphics" / "Particles" / "Meteor" / "_debug"
ALPHA_THRESH = 40


def load_rgba(path: Path) -> np.ndarray:
    return np.array(Image.open(path).convert("RGBA"))


def ball_stats(rgba: np.ndarray):
    """Ball ≈ leading (down-right) mass of the streak — matches perceived head size."""
    mask = rgba[..., 3] > ALPHA_THRESH
    h, w = rgba.shape[:2]
    if not mask.any():
        return w / 2.0, h / 2.0, 1.0

    ys, xs = np.where(mask)
    u = xs.astype(np.float64) + ys.astype(np.float64)
    # Front of the meteor (toward impact direction on this sheet).
    thr = float(np.percentile(u, 70))
    lead = u >= thr
    if not np.any(lead):
        lead = np.ones_like(u, dtype=bool)
    cx = float(xs[lead].mean())
    cy = float(ys[lead].mean())
    d = np.sqrt((xs[lead] - cx) ** 2 + (ys[lead] - cy) ** 2)
    r = float(np.percentile(d, 88))
    return cx, cy, max(r, 1.0)


def main():
    live = sorted(DESCENT.glob("*.png"))
    if not live and not any(BACKUP.glob("*.png")):
        raise SystemExit(f"No frames in {DESCENT}")

    BACKUP.mkdir(parents=True, exist_ok=True)
    # Seed backup only from first-seen originals (never overwrite with normalized).
    for p in live:
        dest = BACKUP / p.name
        if not dest.exists():
            shutil.copy2(p, dest)

    src_frames = sorted(BACKUP.glob("*.png"))
    images = []
    stats = []
    for p in src_frames:
        rgba = load_rgba(p)
        cx, cy, r = ball_stats(rgba)
        images.append((p.name, rgba))
        stats.append((cx, cy, r))
        print(f"{p.name}: {rgba.shape[1]}x{rgba.shape[0]} ball=({cx:.1f},{cy:.1f}) r={r:.1f}")

    radii = np.array([s[2] for s in stats], dtype=float)
    # Match the largest head so early frames upscale (better than crushing late frames).
    target_r = float(np.max(radii))
    print(f"\nTarget ball radius: {target_r:.2f}px (max head)")

    scaled = []
    for (name, rgba), (cx, cy, r) in zip(images, stats):
        factor = target_r / max(r, 1.0)
        h, w = rgba.shape[:2]
        new_w = max(1, int(round(w * factor)))
        new_h = max(1, int(round(h * factor)))
        arr = np.array(
            Image.fromarray(rgba, "RGBA").resize((new_w, new_h), Image.Resampling.LANCZOS)
        )
        scaled.append((name, arr, cx * factor, cy * factor, factor))
        print(f"  scale {name}: r={r:.1f} x{factor:.3f} -> {new_w}x{new_h}")

    pad = int(round(target_r * 1.25))
    max_left = max(int(np.ceil(ncx)) for _, _, ncx, _, _ in scaled)
    max_right = max(int(np.ceil(arr.shape[1] - ncx)) for _, arr, ncx, _, _ in scaled)
    max_up = max(int(np.ceil(ncy)) for _, _, _, ncy, _ in scaled)
    max_down = max(int(np.ceil(arr.shape[0] - ncy)) for _, arr, _, ncy, _ in scaled)
    canvas_w = max_left + max_right + 2 * pad
    canvas_h = max_up + max_down + 2 * pad
    ball_x = max_left + pad
    ball_y = max_up + pad
    print(f"Canvas {canvas_w}x{canvas_h}, ball anchor ({ball_x},{ball_y})")

    DESCENT.mkdir(parents=True, exist_ok=True)
    DEBUG.mkdir(parents=True, exist_ok=True)
    contact = Image.new("RGBA", (canvas_w * len(scaled), canvas_h), (0, 0, 0, 255))

    for i, (name, arr, ncx, ncy, _factor) in enumerate(scaled):
        canvas = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
        x0 = int(round(ball_x - ncx))
        y0 = int(round(ball_y - ncy))
        h, w = arr.shape[:2]
        # Clip if rounding pushes past edges.
        x0c, y0c = max(0, x0), max(0, y0)
        xs = x0c - x0
        ys = y0c - y0
        ww = min(w - xs, canvas_w - x0c)
        hh = min(h - ys, canvas_h - y0c)
        canvas[y0c : y0c + hh, x0c : x0c + ww] = arr[ys : ys + hh, xs : xs + ww]

        # Crosshair at intended ball anchor for debug contact sheet.
        out = Image.fromarray(canvas, "RGBA")
        out.save(DESCENT / name)
        dbg = out.copy()
        px = dbg.load()
        for d in range(-6, 7):
            if 0 <= ball_x + d < canvas_w:
                px[ball_x + d, ball_y] = (0, 255, 0, 255)
            if 0 <= ball_y + d < canvas_h:
                px[ball_x, ball_y + d] = (0, 255, 0, 255)
        contact.paste(dbg, (i * canvas_w, 0))

        vcx, vcy, vr = ball_stats(canvas)
        print(f"wrote {name}: detect=({vcx:.1f},{vcy:.1f}) r={vr:.1f}  anchor=({ball_x},{ball_y})")

    contact_path = DEBUG / "descent_normalized_contact.png"
    contact.save(contact_path)
    print(f"\nOriginals: {BACKUP}")
    print(f"Normalized: {DESCENT}")
    print(f"Contact sheet: {contact_path}")


if __name__ == "__main__":
    main()
