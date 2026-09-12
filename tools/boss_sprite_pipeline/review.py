"""Contact-sheet helpers shared by the review gates (Gate A turntable, Gate B composite)."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw


def direction_row(frames_dir: Path, action: str, out_png: Path, *, frame: int = 0, bg=(90, 90, 90, 255)) -> Path:
    """One row: every direction of `action` at `frame`, labelled, anchor marked."""
    manifest = json.loads((frames_dir / "manifest.json").read_text(encoding="utf-8"))
    keys, res = manifest["directions"], manifest["resolution"]
    ax, ay = manifest["anchor_px"]
    sheet = Image.new("RGBA", (res * len(keys), res), bg)
    draw = ImageDraw.Draw(sheet)
    for i, key in enumerate(keys):
        img = Image.open(frames_dir / action / key / f"{frame:04d}.png").convert("RGBA")
        sheet.alpha_composite(img, (i * res, 0))
        draw.text((i * res + 4, 4), key, fill=(255, 255, 0, 255))
        draw.ellipse((i * res + ax - 3, ay - 3, i * res + ax + 3, ay + 3), outline=(255, 0, 0, 255), width=2)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    return out_png


def composite_on_level(sprite_png: Path, anchor_px: tuple[float, float], level_png: Path, at_xy: tuple[int, int],
                       out_png: Path, *, scale: float = 1.0, crop: int = 600) -> Path:
    """Gate B: drop one trimmed frame onto the painted level at game scale, crop around it."""
    level = Image.open(level_png).convert("RGBA")
    sprite = Image.open(sprite_png).convert("RGBA")
    if scale != 1.0:
        sprite = sprite.resize((max(1, int(sprite.width * scale)), max(1, int(sprite.height * scale))), Image.LANCZOS)
    ax, ay = anchor_px[0] * scale, anchor_px[1] * scale
    x, y = int(at_xy[0] - ax), int(at_xy[1] - ay)
    level.alpha_composite(sprite, (max(0, x), max(0, y)))
    half = crop // 2
    box = (max(0, at_xy[0] - half), max(0, at_xy[1] - half), min(level.width, at_xy[0] + half), min(level.height, at_xy[1] + half))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    level.crop(box).save(out_png)
    return out_png
