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


def _edge_keys(edge: np.ndarray) -> np.ndarray:
    """Each colour that covers a real share of the border.

    A Veo frame often has black bars and a cream field on the same edge.
    One median keeps whichever colour loses the count.
    """
    bins = edge.astype(np.int32) // 16
    ids = bins[:, 0] * 256 + bins[:, 1] * 16 + bins[:, 2]
    uniq, counts = np.unique(ids, return_counts=True)
    keep = uniq[counts >= max(8, int(0.05 * len(edge)))]
    if len(keep) == 0:
        return np.median(edge, axis=0).reshape(1, 3)
    return np.stack([np.median(edge[ids == uid], axis=0) for uid in keep])


def _matte_border(image: Image.Image) -> Image.Image:
    """Clear the sheet colours where they touch the frame edge.

    A pixel in the middle that happens to be the same grey stays. That is the
    armour. Only the field connected to the border goes.
    """
    from scipy import ndimage

    from tools.sprite_assets.remove_bg import _drop_specks

    rgb = np.asarray(image.convert("RGB"))
    height, width, _ = rgb.shape
    edge = np.concatenate([
        rgb[0, :, :],
        rgb[-1, :, :],
        rgb[:, 0, :],
        rgb[:, -1, :],
    ]).astype(np.float32)
    keys = _edge_keys(edge)
    dist = np.abs(rgb.astype(np.float32)[:, :, None, :] - keys[None, None, :, :]).max(axis=3)
    match = dist.min(axis=2)
    near = match <= 32.0
    labels, _count = ndimage.label(near)
    border_ids = np.unique(np.concatenate([
        labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1],
    ]))
    border_ids = border_ids[border_ids > 0]
    background = np.isin(labels, border_ids) if len(border_ids) else np.zeros((height, width), dtype=bool)
    # A gap between the legs is the same field colour, but the body closes it off
    # from the frame edge. Clear those holes when they match the field tightly.
    # A single matching pixel inside armour stays.
    tight = match <= 18.0
    hole_labels, _hole_count = ndimage.label(tight)
    hole_border = np.unique(np.concatenate([
        hole_labels[0, :], hole_labels[-1, :], hole_labels[:, 0], hole_labels[:, -1],
    ]))
    hole_border = hole_border[hole_border > 0]
    enclosed = (hole_labels > 0) & ~np.isin(hole_labels, hole_border) if len(hole_border) else hole_labels > 0
    hole_sizes = np.bincount(hole_labels.ravel())
    big_holes = hole_sizes[hole_labels] >= 24
    cleared = background | (enclosed & big_holes)
    # One pixel of leftover field colour where it touches the new transparency.
    fringe = ndimage.binary_dilation(cleared, iterations=1) & ~cleared & (match <= 40.0)
    cleared = cleared | fringe
    solid = _drop_specks(~cleared, max(12, int(0.0002 * height * width)))
    out = np.zeros((height, width, 4), dtype=np.uint8)
    out[:, :, :3] = rgb
    out[:, :, 3] = np.where(solid, 255, 0).astype(np.uint8)
    return Image.fromarray(out)


def _crop_union(frames: list[Image.Image], pad: int = 2) -> list[Image.Image]:
    """One box around every frame of the clip, so the figure does not jump."""
    from tools.sprite_assets.remove_bg import trim_box

    if not frames:
        return frames
    boxes = [trim_box(frame, pad=0) for frame in frames]
    x0 = min(box[0] for box in boxes)
    y0 = min(box[1] for box in boxes)
    x1 = max(box[2] for box in boxes)
    y1 = max(box[3] for box in boxes)
    width, height = frames[0].size
    box = (
        max(0, x0 - pad),
        max(0, y0 - pad),
        min(width, x1 + pad),
        min(height, y1 + pad),
    )
    return [frame.crop(box) for frame in frames]


def _load_video_frames(path: Path) -> list[Image.Image]:
    """Sample the clip, clear the field, and crop to the figure.

    The flyer cutter wants a long empty-black stretch, and a warrior filling
    the frame never has one. The crop is the same idea: one box for the clip.
    """
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open {path}")
    raw = []
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        raw.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    cap.release()
    if len(raw) < 4:
        raise RuntimeError(f"no frames in {path}")
    step = max(1, len(raw) // 16)
    matted = [_matte_border(Image.fromarray(frame)) for frame in raw[::step][:16]]
    return _crop_union(matted)


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


def sheet_man_height(cells: list[Image.Image]) -> int:
    """Median figure height of the standing men on the sheet.

    A ballista or a tower is as wide as it is tall. A man is not, so the
    machines do not set the scale.
    """
    heights = []
    for image in cells:
        _foot_x, _foot_y, height = foot_and_height(image)
        if height > image.width * 1.35:
            heights.append(height)
    if not heights:
        heights = [foot_and_height(image)[2] for image in cells]
    if not heights:
        raise RuntimeError("no cells to measure")
    return int(round(median(heights)))


def scene_fighter_height(image: Image.Image, band: str = "near") -> int:
    """Median height of the standing fighters in one band of the battle.

    ``near`` is the bottom half. ``center`` is the middle 60 percent of the
    picture. The short specks and the merged clumps are the tails of the
    sizes. A ballista is wider than it is tall, so it is not in this sample.
    """
    from scipy import ndimage

    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    height, width = rgb.shape[:2]
    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    warm = (red > 140) & (green > 110) & (red > blue + 15)
    if int(warm.sum()) < 64:
        sand = np.median(rgb.reshape(-1, 3), axis=0)
    else:
        sand = np.median(rgb[warm], axis=0)
    mark = np.abs(rgb - sand).max(axis=2) > 36
    if band == "center":
        y0, y1 = int(height * 0.20), int(height * 0.80)
        x0, x1 = int(width * 0.20), int(width * 0.80)
        kept = np.zeros_like(mark)
        kept[y0:y1, x0:x1] = mark[y0:y1, x0:x1]
        mark = kept
    else:
        mark[: height // 2, :] = False
    labels, _count = ndimage.label(mark)
    found = []
    for idx, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        area = int((labels[sl] == idx).sum())
        box_h = sl[0].stop - sl[0].start
        box_w = sl[1].stop - sl[1].start
        if area < 80 or box_h < box_w or box_h > height * 0.15 or box_w > width * 0.12:
            continue
        found.append(box_h)
    if len(found) < 4:
        raise RuntimeError("no standing fighters in the chosen part of the battle")
    found.sort()
    start = int(len(found) * 0.40)
    stop = max(start + 1, int(len(found) * 0.85))
    core = found[start:stop]
    return int(core[len(core) // 2])


def height_times_man(size, figure: int, man_height: int) -> float:
    """How many standing men tall this figure should be.

    A size from the score wins. Without one, keep the height of the drawing.
    """
    if isinstance(size, (int, float)) and not isinstance(size, bool):
        return min(2.5, max(0.5, float(size)))
    if man_height <= 0:
        return 1.0
    return figure / man_height


def battle_scale(scene: Image.Image, cells: list[Image.Image], band: str = "near") -> float:
    """How much smaller a man is in the battle than on the sheet.

    The same fraction applies to every cell. A ballista that is not in the
    battle keeps the size it had next to the men on the sheet.
    """
    return scene_fighter_height(scene, band) / sheet_man_height(cells)


def _scale_to_height(image: Image.Image, target: int) -> Image.Image:
    _fx, _fy, height = foot_and_height(image)
    if height == target:
        return image
    scale = target / height
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def fit_actions(
    actions: dict[str, list[Image.Image]],
    target_height: int | None = None,
) -> dict[str, list[Image.Image]]:
    """One height, one bottom-centre foot point, one canvas for every frame.

    Pass the height the figure should stand at. That is the cut cell's figure
    height times the battle scale. Without it, the height is the median of the
    idle frames.
    Frames are not trimmed one by one: that is what makes the sprite jump.
    """
    if target_height is None:
        target = int(round(median(foot_and_height(frame)[2] for frame in actions["idle"])))
    else:
        target = int(target_height)
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
