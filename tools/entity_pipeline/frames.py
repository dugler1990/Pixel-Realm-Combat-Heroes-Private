"""Split black action sheets, line the feet up, and pack the monster folders."""
from __future__ import annotations

from pathlib import Path
from statistics import median

import numpy as np
from PIL import Image

from tools.sprite_assets.cut_sheet import cells_from_grid, cut_cells, detect_gutter_grid
from tools.sprite_assets.pack_sequence import pack_sequence
from tools.sprite_assets.remove_bg import matte_black_bg

ACTIONS = ("idle", "move", "attack")


def _load_sheet_frames(path: Path) -> list[Image.Image]:
    """Frames from one black sheet, via the existing gutter cutter, then the black matte.

    The cutter's default percentile is for a thin gutter on a full sheet. An action
    sheet is the other way around, mostly black, so a single cell is split again
    with the black field itself as the gutter.
    """
    image = Image.open(path)
    rows, cols = detect_gutter_grid(image)
    cells = cells_from_grid(rows, cols, inset=(2, 2, 2, 2))
    if len(cells) <= 1:
        rows, cols = detect_gutter_grid(
            image, row_percentile=50, col_percentile=50, skip_first_row_span=False,
        )
        cells = cells_from_grid(rows, cols, inset=(2, 2, 2, 2))
    if not cells:
        raise RuntimeError(f"no frames found in {path}")
    frames = []
    for _cell, crop in cut_cells(image, cells):
        frames.append(matte_black_bg(crop))
    return frames


def _load_video_frames(path: Path) -> list[Image.Image]:
    """A black-background video goes through extract_black_loop, then the fit step."""
    import tempfile

    from tools.sprite_assets.extract_black_loop import extract

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "frames"
        extract(path, out)
        frames = [Image.open(p).convert("RGBA") for p in sorted(out.glob("*.png"))]
        # Keep the pixels; the temp dir is about to go away.
        return [frame.copy() for frame in frames]


def load_action(path: Path) -> list[Image.Image]:
    path = Path(path)
    if path.is_dir():
        frames = [Image.open(p).convert("RGBA") for p in sorted(path.glob("*.png")) if not p.name.startswith("_")]
        if not frames:
            raise RuntimeError(f"no frames in {path}")
        return frames
    if path.suffix.lower() in {".mp4", ".webm", ".mov", ".avi"}:
        return _load_video_frames(path)
    return _load_sheet_frames(path)


def _mask(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGBA"))[:, :, 3] > 16


def foot_and_height(image: Image.Image) -> tuple[int, int, int]:
    """The feet, and the figure's height down to them.

    A thin weapon below the stance is not the feet: the foot row is the lowest row
    that is still a real slice of the body.
    """
    mask = _mask(image)
    width, height = image.size
    if not mask.any():
        return width // 2, height - 1, max(1, height)
    rows = mask.sum(axis=1)
    peak = int(rows.max())
    wide = np.flatnonzero(rows >= max(4, int(0.12 * peak)))
    foot_y = int(wide[-1]) if len(wide) else int(np.flatnonzero(rows > 0)[-1])
    top_y = int(np.flatnonzero(rows > 0)[0])
    foot_x = _widest_run_center(mask[foot_y])
    return foot_x, foot_y, max(1, foot_y - top_y + 1)


def _widest_run_center(row: np.ndarray) -> int:
    """Centre of the widest solid run on this row. A thin sword beside the foot is ignored."""
    xs = np.flatnonzero(row)
    if len(xs) == 0:
        return 0
    splits = np.flatnonzero(np.diff(xs) > 1)
    starts = np.r_[xs[0], xs[splits + 1]]
    ends = np.r_[xs[splits], xs[-1]]
    widths = ends - starts
    i = int(np.argmax(widths))
    return int((int(starts[i]) + int(ends[i])) // 2)


def _scale_to_height(image: Image.Image, target: int) -> Image.Image:
    _fx, _fy, height = foot_and_height(image)
    if height == target:
        return image
    scale = target / height
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def fit_actions(
    actions: dict[str, list[Image.Image]],
) -> dict[str, list[Image.Image]]:
    """One height, one bottom-centre foot point, one canvas for every frame.

    The height is the median figure height of the idle frames. Frames are not
    trimmed one by one: that is what makes the sprite jump and change size.
    """
    idle = actions["idle"]
    target = int(round(median(foot_and_height(frame)[2] for frame in idle)))
    target = max(1, target)
    scaled = {name: [_scale_to_height(frame, target) for frame in frames] for name, frames in actions.items()}

    placed_metrics = {
        name: [foot_and_height(frame) for frame in frames] for name, frames in scaled.items()
    }
    left = 0
    right = 0
    above = 0
    below = 0
    for name, frames in scaled.items():
        for frame, (foot_x, foot_y, _h) in zip(frames, placed_metrics[name]):
            left = max(left, foot_x)
            right = max(right, frame.width - foot_x)
            above = max(above, foot_y)
            below = max(below, frame.height - 1 - foot_y)
    canvas_w = left + right + 2
    canvas_h = above + below + 2
    anchor_x = left + 1
    anchor_y = above + 1

    fitted: dict[str, list[Image.Image]] = {}
    for name, frames in scaled.items():
        row = []
        for frame, (foot_x, foot_y, _h) in zip(frames, placed_metrics[name]):
            canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            canvas.alpha_composite(frame, (anchor_x - foot_x, anchor_y - foot_y))
            row.append(canvas)
        fitted[name] = row
    return fitted


def pack_monster(name: str, fitted: dict[str, list[Image.Image]], root: Path | None = None) -> Path:
    """Write Graphics/Monsters/<name>/{idle,move,attack}/00.png… and a three-row contact."""
    monster = Path(root) if root is not None else Path("Graphics/Monsters") / name
    for action in ACTIONS:
        frames = fitted[action]
        pack_sequence([(str(i), frame) for i, frame in enumerate(frames)], monster / action, clear=True)
    _write_rows(fitted, monster / "_contact.png")
    return monster


def _write_rows(fitted: dict[str, list[Image.Image]], path: Path) -> None:
    thumb_h = 96
    gap = 4
    widths = []
    thumbs: dict[str, list[Image.Image]] = {}
    for action in ACTIONS:
        row = []
        for frame in fitted[action]:
            scale = thumb_h / frame.height
            size = (max(1, round(frame.width * scale)), thumb_h)
            row.append(frame.resize(size, Image.Resampling.BILINEAR))
        thumbs[action] = row
        widths.append(sum(im.width for im in row) + gap * (len(row) + 1))
    sheet_w = max(widths) if widths else thumb_h
    sheet_h = thumb_h * len(ACTIONS) + gap * (len(ACTIONS) + 1)
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (20, 20, 24, 255))
    y = gap
    for action in ACTIONS:
        x = gap
        for thumb in thumbs[action]:
            sheet.paste(thumb, (x, y), thumb)
            x += thumb.width + gap
        y += thumb_h + gap
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
