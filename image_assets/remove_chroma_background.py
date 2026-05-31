"""
Remove distinct video-export backgrounds (e.g. light blue) and letterbox black bars.

Uses border flood-fill with Lab color distance — does not assume a single flat RGB
everywhere, but seeds from frame edges (black bars + dominant backdrop on edges).

Usage:
  python remove_chroma_background.py <folder> [fuzz] [--crop] [--bg R,G,B] [--no-black]

Output: <folder>/cleaned/*.png
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import deque

import numpy as np
from PIL import Image

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_BLACK_MAX_CHANNEL = 28
_EDGE_BAND_FRAC = 0.04
_EDGE_BAND_MIN = 4
_DEFAULT_FUZZ = 18.0


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """rgb: (N, 3) uint8 -> (N, 3) float Lab."""
    x = rgb.astype(np.float64) / 255.0
    mask = x > 0.04045
    x_lin = np.where(mask, ((x + 0.055) / 1.055) ** 2.4, x / 12.92)
    r, g, b = x_lin[:, 0], x_lin[:, 1], x_lin[:, 2]
    x_ = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y_ = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z_ = r * 0.0193339 + g * 0.1191920 + b * 0.9503041

    x_ = np.where(x_ > 0.008856, x_ ** (1 / 3), (7.787 * x_) + (16 / 116))
    y_ = np.where(y_ > 0.008856, y_ ** (1 / 3), (7.787 * y_) + (16 / 116))
    z_ = np.where(z_ > 0.008856, z_ ** (1 / 3), (7.787 * z_) + (16 / 116))

    l = (116 * y_) - 16
    a = 500 * (x_ - y_)
    b_lab = 200 * (y_ - z_)
    return np.stack([l, a, b_lab], axis=1)


def _delta_e(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    d = lab1 - lab2
    return np.sqrt(np.sum(d * d, axis=-1))


def _is_near_black(rgb: np.ndarray) -> np.ndarray:
    return (
        (rgb[..., 0] <= _BLACK_MAX_CHANNEL)
        & (rgb[..., 1] <= _BLACK_MAX_CHANNEL)
        & (rgb[..., 2] <= _BLACK_MAX_CHANNEL)
    )


def _edge_band_indices(h: int, w: int) -> np.ndarray:
    t = max(_EDGE_BAND_MIN, int(min(h, w) * _EDGE_BAND_FRAC))
    ys = []
    xs = []
    for y in range(h):
        for x in range(w):
            if y < t or y >= h - t or x < t or x >= w - t:
                ys.append(y)
                xs.append(x)
    return np.array(ys, dtype=np.int32), np.array(xs, dtype=np.int32)


def _estimate_backdrop_lab(rgb: np.ndarray, manual_bg: tuple[int, int, int] | None) -> np.ndarray | None:
    if manual_bg is not None:
        sample = np.array([[manual_bg[0], manual_bg[1], manual_bg[2]]], dtype=np.uint8)
        return _rgb_to_lab(sample)[0]

    h, w = rgb.shape[:2]
    ey, ex = _edge_band_indices(h, w)
    edge_rgb = rgb[ey, ex]
    not_black = ~_is_near_black(edge_rgb)
    candidates = edge_rgb[not_black]
    if len(candidates) < 8:
        candidates = edge_rgb
    if len(candidates) == 0:
        return None
    labs = _rgb_to_lab(candidates)
    return np.median(labs, axis=0)


def _flood_clear_background(
    rgba: np.ndarray,
    fuzz: float,
    key_black: bool,
    manual_bg: tuple[int, int, int] | None,
) -> np.ndarray:
    h, w = rgba.shape[:2]
    rgb = rgba[:, :, :3]
    alpha = rgba[:, :, 3].copy()
    lab_img = _rgb_to_lab(rgb.reshape(-1, 3)).reshape(h, w, 3)
    bg_lab = _estimate_backdrop_lab(rgb, manual_bg)

    black = _is_near_black(rgb) if key_black else np.zeros((h, w), dtype=bool)
    if bg_lab is not None:
        de = _delta_e(lab_img, bg_lab.reshape(1, 1, 3))
        similar = de <= fuzz
    else:
        similar = np.zeros((h, w), dtype=bool)

    removable = black | similar
    visited = np.zeros((h, w), dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    for x in range(w):
        queue.append((0, x))
        queue.append((h - 1, x))
    for y in range(h):
        queue.append((y, 0))
        queue.append((y, w - 1))

    while queue:
        y, x = queue.popleft()
        if visited[y, x]:
            continue
        visited[y, x] = True
        if not removable[y, x]:
            continue
        alpha[y, x] = 0
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                queue.append((ny, nx))

    out = rgba.copy()
    out[:, :, 3] = alpha
    return out


def _crop_transparent(rgba: np.ndarray) -> np.ndarray:
    alpha = rgba[:, :, 3]
    ys, xs = np.where(alpha > 0)
    if len(xs) == 0:
        return rgba
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    return rgba[y0:y1, x0:x1]


def process_image(
    in_path: str,
    out_path: str,
    fuzz: float,
    key_black: bool,
    crop: bool,
    manual_bg: tuple[int, int, int] | None,
) -> None:
    img = Image.open(in_path).convert("RGBA")
    rgba = np.array(img)
    rgba = _flood_clear_background(rgba, fuzz=fuzz, key_black=key_black, manual_bg=manual_bg)
    if crop:
        rgba = _crop_transparent(rgba)
    Image.fromarray(rgba).save(out_path)


def process_folder(
    folder_path: str,
    fuzz: float = _DEFAULT_FUZZ,
    key_black: bool = True,
    crop: bool = False,
    manual_bg: tuple[int, int, int] | None = None,
) -> int:
    folder_path = os.path.abspath(folder_path)
    if not os.path.isdir(folder_path):
        print("Folder does not exist:", folder_path)
        return 0

    out_dir = os.path.join(folder_path, "cleaned")
    os.makedirs(out_dir, exist_ok=True)

    files = sorted(
        f
        for f in os.listdir(folder_path)
        if f.lower().endswith(_IMAGE_EXTS) and f != "cleaned"
    )
    if not files:
        print("No images in:", folder_path)
        return 0

    print("Folder:", folder_path)
    print("Fuzz (Lab deltaE):", fuzz, "| key black:", key_black, "| crop:", crop, "| manual bg:", manual_bg)

    count = 0
    for name in files:
        in_path = os.path.join(folder_path, name)
        if not os.path.isfile(in_path):
            continue
        out_path = os.path.join(out_dir, os.path.splitext(name)[0] + ".png")
        print("Processing:", name)
        process_image(in_path, out_path, fuzz, key_black, crop, manual_bg)
        count += 1

    print("Done. Processed", count, "images ->", out_dir)
    return count


def _parse_bg(value: str) -> tuple[int, int, int]:
    parts = [int(p.strip()) for p in value.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("Expected R,G,B")
    return tuple(parts)  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Flood-remove letterbox black and edge-connected backdrop from sprite frames."
    )
    parser.add_argument("folder", help="Folder of extracted frames")
    parser.add_argument(
        "fuzz",
        nargs="?",
        type=float,
        default=_DEFAULT_FUZZ,
        help=f"Lab deltaE tolerance (default {_DEFAULT_FUZZ})",
    )
    parser.add_argument("--crop", action="store_true", help="Crop to non-transparent bbox after keying")
    parser.add_argument("--no-black", action="store_true", help="Do not key letterbox black from edges")
    parser.add_argument("--bg", type=_parse_bg, metavar="R,G,B", help="Manual backdrop color (skip auto-detect)")
    args = parser.parse_args(argv)

    process_folder(
        args.folder,
        fuzz=args.fuzz,
        key_black=not args.no_black,
        crop=args.crop,
        manual_bg=args.bg,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
