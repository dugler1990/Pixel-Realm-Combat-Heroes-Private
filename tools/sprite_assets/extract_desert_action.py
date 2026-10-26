"""Cut the tumble, the ground crash, and the fire breath off the desert clips.

The flap loop is a black sheet, so a black matte works for it. These shots are the
same creature over sand, with the camera drifting, so the cut is a salient-object
mask (rembg) plus the bright fire, which that mask drops. Frames of one action
share one crop so the dive and the tumble keep the path that is already in the picture.

    python tools/sprite_assets/extract_desert_action.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from rembg import new_session, remove

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.sprite_assets.pack_sequence import pack_sequence, write_contact_sheet

# About the flap strip's height. Actions are scaled so the body matches that.
TARGET_HEIGHT = 180
DOWNLOADS = Path.home() / "Downloads"
HAILUO = DOWNLOADS / (
    "hailuo-2_3_I_would_like_this_boss_moving_around_and_doing_some_attacks_"
    "this_is_a_literal_sc-0.mp4"
)
VEO = DOWNLOADS / (
    "veo-3.1-lite_I_would_like_this_boss_moving_around_and_doing_some_attacks_"
    "this_is_a_literal_sc-0.mp4"
)


def _read_frames(path: Path) -> tuple[list[np.ndarray], float]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 24.0)
    frames = []
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    cap.release()
    if not frames:
        raise SystemExit(f"no frames in {path}")
    return frames, fps


def _content_box(frame: np.ndarray) -> tuple[int, int, int, int]:
    col = frame.mean(axis=(0, 2))
    row = frame.mean(axis=(1, 2))
    xs = np.where(col > 12)[0]
    ys = np.where(row > 12)[0]
    if len(xs) == 0 or len(ys) == 0:
        h, w = frame.shape[:2]
        return 0, 0, w, h
    return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1


def _fire_mask(rgb: np.ndarray) -> np.ndarray:
    """Bright flame only. Sunlit sand is bright too, but it is grey, not orange."""
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)
    warm = (r > 160) & (g > 40) & (g > b) & (r > b + 90)
    return warm.astype(np.uint8)


def _add_fire(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    hot = _fire_mask(rgb)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(hot, 8)
    if count <= 1:
        return alpha
    touch = cv2.dilate(
        (alpha > 80).astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)),
    )
    out = np.array(alpha, copy=True)
    for i, area in enumerate(stats[1:, cv2.CC_STAT_AREA], start=1):
        if area < 400:
            continue
        blob = labels == i
        # A red wing passes the hue test. Flame is actually bright.
        if int(np.median(rgb[:, :, 0][blob])) < 190:
            continue
        if touch[blob].any():
            out[blob] = 255
    return out


def _matte(rgb: np.ndarray, session) -> np.ndarray:
    cut = np.asarray(remove(Image.fromarray(rgb), session=session))
    alpha = _add_fire(rgb, np.array(cut[:, :, 3], copy=True))
    return np.dstack([rgb, alpha])


def _opaque_box(alpha: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(alpha > 24)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _cut(video: Path, start: int, end: int, step: int, out_dir: Path, session) -> None:
    frames, fps = _read_frames(video)
    x0, y0, x1, y1 = _content_box(frames[0])
    cropped = [f[y0:y1, x0:x1] for f in frames]
    end = min(end, len(cropped))
    chosen = list(range(start, end, step))
    matted = [_matte(cropped[i], session) for i in chosen]
    boxes = [_opaque_box(m[:, :, 3]) for m in matted]
    good = [b for b in boxes if b is not None]
    if not good:
        raise SystemExit(f"nothing visible in {video.name} {start}:{end}")
    ux0 = max(0, min(b[0] for b in good) - 4)
    uy0 = max(0, min(b[1] for b in good) - 4)
    ux1 = min(matted[0].shape[1], max(b[2] for b in good) + 4)
    uy1 = min(matted[0].shape[0], max(b[3] for b in good) + 4)

    heights = [b[3] - b[1] for b in good]
    scale = TARGET_HEIGHT / max(float(np.median(heights)), 1.0)
    scale = float(np.clip(scale, 0.12, 1.2))

    pil_frames = []
    for rgba in matted:
        im = Image.fromarray(rgba[uy0:uy1, ux0:ux1], "RGBA")
        if abs(scale - 1.0) > 0.02:
            size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
            im = im.resize(size, Image.Resampling.LANCZOS)
        pil_frames.append(im)

    first = np.asarray(pil_frames[0])
    # Anchor on the body. The flame would pull the center out along the jet.
    body = (first[:, :, 3] > 40) & (_fire_mask(first[:, :, :3]) == 0)
    ys, xs = np.nonzero(body)
    if len(xs) == 0:
        ys, xs = np.nonzero(first[:, :, 3] > 40)
    if len(xs) == 0:
        anchor = [pil_frames[0].width // 2, pil_frames[0].height // 2]
    else:
        anchor = [int(round(float(xs.mean()))), int(round(float(ys.mean())))]

    out_dir.mkdir(parents=True, exist_ok=True)
    pack_sequence([(str(i), im) for i, im in enumerate(pil_frames)], out_dir)
    write_contact_sheet(pil_frames, out_dir.parent / f"_{out_dir.name}.png", cols=8, cell=140)
    meta = {
        "frame_ms": round(1000.0 * step / fps, 3),
        "source_fps": fps,
        "step": step,
        "start_frame": start,
        "end_frame": end,
        "count": len(pil_frames),
        "size": [pil_frames[0].width, pil_frames[0].height],
        "anchor": anchor,
    }
    (out_dir / "clip.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(
        f"{out_dir.name}: {len(pil_frames)} frames {pil_frames[0].size} "
        f"scale {scale:.2f} anchor {anchor}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=_ROOT / "Graphics" / "Monsters" / "flyer")
    args = parser.parse_args()
    session = new_session("u2net")
    # Hurt is the air tumble. Crash is the dive into the ground. Breath is the jet after.
    _cut(HAILUO, 48, 208, 2, args.out / "hurt", session)
    _cut(VEO, 68, 156, 2, args.out / "crash", session)
    _cut(VEO, 160, 192, 1, args.out / "breath", session)


if __name__ == "__main__":
    main()
