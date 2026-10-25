"""Write numbered frame folders and contact sheets."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw


def pack_sequence(
    frames: Sequence[tuple[str, Image.Image]],
    out_dir: Path,
    *,
    clear: bool = True,
) -> list[Path]:
    """Save frames as 00.png, 01.png, ... under out_dir.

    ``frames`` items are (logical_name, image); order is kept.
    """
    out_dir = Path(out_dir)
    if clear and out_dir.exists():
        for p in out_dir.glob("*.png"):
            p.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, (name, img) in enumerate(frames):
        path = out_dir / f"{i:02d}.png"
        img.convert("RGBA").save(path)
        paths.append(path)
    return paths


def write_contact_sheet(
    frames: Sequence[Image.Image],
    path: Path,
    *,
    cols: int = 8,
    cell: int = 128,
    pad: int = 4,
    bg=(20, 20, 24, 255),
) -> Path:
    frames = list(frames)
    if not frames:
        raise ValueError("no frames")
    cols = max(1, min(cols, len(frames)))
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cell + pad * (cols + 1), rows * cell + pad * (rows + 1)), bg)
    draw = ImageDraw.Draw(sheet)
    for i, frame in enumerate(frames):
        r, c = divmod(i, cols)
        x = pad + c * (cell + pad)
        y = pad + r * (cell + pad)
        thumb = frame.convert("RGBA").copy()
        thumb.thumbnail((cell - 2, cell - 2), Image.Resampling.LANCZOS)
        ox = x + (cell - thumb.size[0]) // 2
        oy = y + (cell - thumb.size[1]) // 2
        sheet.paste(thumb, (ox, oy), thumb)
        draw.rectangle([x, y, x + cell - 1, y + cell - 1], outline=(60, 60, 70, 255))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path
