"""Stage 5: trim rendered frames and install them in the engine's monster layout.

    frames/<action>/<dir>/NNNN.png  →  <install_root>/<name>/<action>/<dir>/Sprite-NNNN.png
                                       <install_root>/<name>/manifest.json
                                       <workdir>/pack/contact_sheet.png

Two trim modes:

``union`` (default) — one box for the whole set, so every installed frame has the same size
and the manifest anchor is one fixed pixel. Simple, and what the fox shipped with.

``per_frame`` — each frame is cropped to its *own* opaque bbox and the manifest records that
frame's anchor. The union box is as large as the widest pose in any direction (a wing spread
or a lunge), so most frames are mostly empty: on the 650 px demon this is the difference
between 1.3 GB and a few hundred MB, with identical pixels on screen. The engine plants
``frames[action][dir][i]["anchor"]`` instead of the one global anchor.

Either way the anchor is the model's ground-contact pixel, not the mask's lowest opaque row —
which would wobble with the ground shadow.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

CONTACT_MAX_COLS = 12
CONTACT_CELL = 96
# Cycles' denoised shadow-catcher pass leaves a 1–8/255 alpha veil over the whole
# frame; anything under this is cleared so trims and masks see only the sprite.
ALPHA_FLOOR = 10


def _frame_paths(frames_dir: Path, manifest: dict):
    for action, spec in manifest["actions"].items():
        for key in manifest["directions"]:
            folder = frames_dir / action / key
            paths = sorted(folder.glob("*.png"))
            if len(paths) != spec["frames"]:
                raise SystemExit(f"{folder}: expected {spec['frames']} frames, found {len(paths)}")
            yield action, key, paths


def clean_alpha(img: Image.Image, alpha_floor: int) -> Image.Image:
    arr = np.asarray(img.convert("RGBA")).copy()
    arr[:, :, 3][arr[:, :, 3] < alpha_floor] = 0
    return Image.fromarray(arr, "RGBA")


def union_alpha_bbox(frames_dir: Path, manifest: dict, alpha_floor: int):
    x0 = y0 = None
    x1 = y1 = -1
    for _, _, paths in _frame_paths(frames_dir, manifest):
        for path in paths:
            alpha = np.asarray(clean_alpha(Image.open(path), alpha_floor))[:, :, 3]
            ys, xs = np.nonzero(alpha > 0)
            if not len(xs):
                continue
            x0 = int(xs.min()) if x0 is None else min(x0, int(xs.min()))
            y0 = int(ys.min()) if y0 is None else min(y0, int(ys.min()))
            x1, y1 = max(x1, int(xs.max())), max(y1, int(ys.max()))
    if x0 is None:
        raise SystemExit("every frame is fully transparent")
    return x0, y0, x1 + 1, y1 + 1


def per_frame_boxes(img: Image.Image, pad: int = 2):
    """That frame's own opaque bbox, padded, clamped to the image."""
    bbox = img.getbbox()
    if bbox is None:
        return (0, 0, 1, 1)
    l, t_, r, b = bbox
    w, h = img.size
    return (max(l - pad, 0), max(t_ - pad, 0), min(r + pad, w), min(b + pad, h))


def pack(workdir: Path, install_root: Path, *, name: str | None = None, keep_existing: bool = False,
         alpha_floor: int = ALPHA_FLOOR, trim: str = "union") -> Path:
    frames_dir = workdir / "frames"
    manifest = json.loads((frames_dir / "manifest.json").read_text(encoding="utf-8"))
    name = name or manifest["name"]
    box = union_alpha_bbox(frames_dir, manifest, alpha_floor)
    left, top, right, bottom = box
    ax, ay = manifest["anchor_px"]

    dest = install_root / name
    if dest.exists() and not keep_existing:
        for action in manifest["actions"]:
            shutil.rmtree(dest / action, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    trimmed: dict[tuple[str, str], list[Image.Image]] = {}
    per_frame_meta: dict[str, dict[str, list]] = {}
    for action, key, paths in _frame_paths(frames_dir, manifest):
        out_dir = dest / action / key
        out_dir.mkdir(parents=True, exist_ok=True)
        frames = []
        for index, path in enumerate(paths):
            cleaned = clean_alpha(Image.open(path), alpha_floor)
            if trim == "per_frame":
                fb = per_frame_boxes(cleaned)
                img = cleaned.crop(fb)
                # anchor relative to THIS frame's crop
                per_frame_meta.setdefault(action, {}).setdefault(key, []).append(
                    {"size": [fb[2] - fb[0], fb[3] - fb[1]],
                     "anchor": [round(ax - fb[0], 2), round(ay - fb[1], 2)]})
            else:
                img = cleaned.crop(box)
            img.save(out_dir / f"Sprite-{index:04d}.png")
            frames.append(img)
        trimmed[(action, key)] = frames

    installed = dict(manifest)
    installed.update({
        "frame_size": [right - left, bottom - top],
        "anchor_px": [round(ax - left, 2), round(ay - top, 2)],
        "trim_box": list(box),
        "alpha_floor": alpha_floor,
        "trim": trim,
        "layout": "<action>/<dir>/Sprite-NNNN.png",
    })
    if trim == "per_frame":
        # every frame has its own size and anchor; the global anchor_px above is the union
        # fallback for readers that do not understand per-frame trim
        installed["frames"] = per_frame_meta
    (dest / "manifest.json").write_text(json.dumps(installed, indent=2), encoding="utf-8")

    pack_dir = workdir / "pack"
    pack_dir.mkdir(exist_ok=True)
    sheet = contact_sheet(trimmed, installed)
    sheet.save(pack_dir / "contact_sheet.png")
    return dest


def contact_sheet(trimmed, manifest) -> Image.Image:
    w, h = manifest["frame_size"]
    scale = min(1.0, CONTACT_CELL / max(w, h))
    cw, ch = max(1, int(w * scale)), max(1, int(h * scale))
    label_w = 40
    blocks = []
    for action, spec in manifest["actions"].items():
        n = spec["frames"]
        cols = min(n, CONTACT_MAX_COLS)
        picks = [round(i * (n - 1) / max(1, cols - 1)) for i in range(cols)] if n > 1 else [0]
        rows = manifest["directions"]
        block = Image.new("RGBA", (label_w + cols * cw, 16 + len(rows) * ch), (70, 70, 70, 255))
        draw = ImageDraw.Draw(block)
        draw.text((4, 2), f"{action}  ({n} frames @ {spec['fps']:g} fps)", fill=(255, 255, 0, 255))
        for r, key in enumerate(rows):
            draw.text((4, 16 + r * ch + ch // 2 - 5), key, fill=(255, 255, 255, 255))
            for c, idx in enumerate(picks):
                src = trimmed[(action, key)][idx]
                cell = src.resize((cw, ch), Image.LANCZOS)
                block.alpha_composite(cell, (label_w + c * cw, 16 + r * ch))
        ax, ay = manifest["anchor_px"]
        for r in range(len(rows)):
            x, y = label_w + int(ax * scale), 16 + r * ch + int(ay * scale)
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), outline=(255, 0, 0, 255))
        blocks.append(block)
    width = max(b.width for b in blocks)
    sheet = Image.new("RGBA", (width, sum(b.height + 4 for b in blocks)), (50, 50, 50, 255))
    y = 0
    for b in blocks:
        sheet.alpha_composite(b, (0, y))
        y += b.height + 4
    return sheet


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir", type=Path)
    ap.add_argument("--install-root", type=Path, default=Path("Graphics/Monsters"))
    ap.add_argument("--name", default=None)
    args = ap.parse_args()
    print("installed ->", pack(args.workdir.resolve(), args.install_root.resolve(), name=args.name))
