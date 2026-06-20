from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _resample():
    return getattr(Image, "Resampling", Image).LANCZOS


def _iter_images(paths, max_images):
    found = []
    for raw_path in paths or []:
        path = Path(raw_path)
        if not path.exists():
            continue
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(p for p in path.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS))
        if len(found) >= max_images:
            return found[:max_images]
    return found[:max_images]


def build_asset_contact_sheet(asset_paths, output_path, max_images=48, cell_size=128, columns=8):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    images = _iter_images(asset_paths, max_images=max_images)
    columns = max(1, int(columns))
    cell_size = max(32, int(cell_size))
    rows = max(1, math.ceil(max(1, len(images)) / columns))
    sheet = Image.new("RGBA", (columns * cell_size, rows * cell_size), (22, 26, 31, 255))
    draw = ImageDraw.Draw(sheet, "RGBA")
    font = ImageFont.load_default()

    for idx, path in enumerate(images):
        col = idx % columns
        row = idx // columns
        x = col * cell_size
        y = row * cell_size
        try:
            img = Image.open(path).convert("RGBA")
        except Exception:
            continue
        scale = min((cell_size - 20) / max(1, img.width), (cell_size - 32) / max(1, img.height), 1.0)
        w = max(1, int(img.width * scale))
        h = max(1, int(img.height * scale))
        img = img.resize((w, h), _resample())
        sheet.alpha_composite(img, (x + (cell_size - w) // 2, y + 6 + (cell_size - 32 - h) // 2))
        label = path.stem[:18]
        draw.text((x + 4, y + cell_size - 18), label, fill=(230, 230, 230, 220), font=font)
        draw.rectangle((x, y, x + cell_size - 1, y + cell_size - 1), outline=(255, 255, 255, 35))

    sheet.convert("RGB").save(output_path)
    return {"output_path": str(output_path), "image_count": len(images)}

