"""Cut one wingbeat from a black-background video into a right-facing move folder.

The black matte is tools.sprite_assets.remove_bg.matte_black_bg. Frames share one
crop (the union of the visible pixels) so the body stays registered, then pack_sequence
writes 00.png, 01.png, ...

    python tools/sprite_assets/extract_black_loop.py VIDEO --out Graphics/Monsters/flyer/move
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.sprite_assets.pack_sequence import pack_sequence, write_contact_sheet
from tools.sprite_assets.remove_bg import matte_black_bg, trim_box

TARGET_HEIGHT = 200
# One sprite frame per this many source frames. 2 keeps a 24 fps flap near 12 fps.
SAMPLE_STEP = 2


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


def _black_fraction(rgb: np.ndarray) -> float:
    """Share of the frame that is still the sheet. Wing tips on the edge do not move this."""
    return float((rgb.max(axis=2) < 18).mean())


def _black_run(frames: list[np.ndarray]) -> tuple[int, int]:
    """The stretch after the fade, once the sheet is black. Brief edge hits stay inside it."""
    dark = [_black_fraction(f) >= 0.8 for f in frames]
    best = None
    i = 0
    while i < len(dark):
        if not dark[i]:
            i += 1
            continue
        j = i
        while j < len(dark) and dark[j]:
            j += 1
        if best is None or (j - i) > (best[1] - best[0]):
            best = (i, j)
        i = j
    if best is None or best[1] - best[0] < 24:
        raise SystemExit("no black-background stretch long enough for a loop")
    return best


def _loop_end(frames: list[np.ndarray], start: int, stop: int) -> int:
    """First return to the pose at `start`, inside [start, stop)."""
    ref = cv2.resize(frames[start], (160, 90)).astype(np.float32)
    diffs = []
    for i in range(start, stop):
        small = cv2.resize(frames[i], (160, 90)).astype(np.float32)
        diffs.append(float(np.mean(np.abs(small - ref))))
    valleys = []
    for i in range(16, len(diffs) - 1):
        if diffs[i] <= diffs[i - 1] and diffs[i] <= diffs[i + 1]:
            valleys.append(i)
    if not valleys:
        raise SystemExit("could not find the loop point in the black stretch")
    floor = min(diffs[i] for i in valleys)
    for i in valleys:
        if diffs[i] <= floor * 1.25 + 0.5:
            return start + i
    return start + valleys[0]


def _union_box(images: list[Image.Image], pad: int = 2) -> tuple[int, int, int, int]:
    boxes = [trim_box(im, pad=0) for im in images]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    w = images[0].size[0]
    h = images[0].size[1]
    return (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))


def extract(video: Path, out_dir: Path, height: int = TARGET_HEIGHT) -> dict:
    frames, fps = _read_frames(video)
    run_start, run_stop = _black_run(frames)
    # A few frames in, so the fade's last grey border is not the loop pose.
    start = min(run_start + 8, run_stop - 24)
    end = _loop_end(frames, start, run_stop)
    chosen = list(range(start, end, SAMPLE_STEP))
    if len(chosen) < 4:
        raise SystemExit(f"loop {start}:{end} is too short to sample")

    matted = [matte_black_bg(Image.fromarray(frames[i])) for i in chosen]
    box = _union_box(matted)
    cropped = [im.crop(box) for im in matted]
    src_w, src_h = cropped[0].size
    dst_h = int(height)
    dst_w = max(1, round(src_w * dst_h / src_h))
    scaled = [
        im.resize((dst_w, dst_h), Image.Resampling.LANCZOS) for im in cropped
    ]

    out_dir = Path(out_dir)
    pack_sequence([(str(i), im) for i, im in enumerate(scaled)], out_dir, clear=True)
    write_contact_sheet(scaled, out_dir.parent / "_contact.png", cols=8, cell=160)
    meta = {
        "frame_ms": round(1000.0 * SAMPLE_STEP / fps, 3),
        "source_fps": fps,
        "step": SAMPLE_STEP,
        "start_frame": start,
        "end_frame": end,
        "count": len(scaled),
        "size": [dst_w, dst_h],
    }
    (out_dir.parent / "clip.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--height", type=int, default=TARGET_HEIGHT)
    args = ap.parse_args(argv)
    meta = extract(args.video, args.out, args.height)
    print(json.dumps(meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
