"""Videos of an installed boss playing in the engine's own draw path, one per action + a grid.

    py -3.12 tools/boss_sprite_pipeline/preview_videos.py demon [--dir s] [--scale 0.5] [--loops 3]

For each action writes <workdir>/preview_video/<action>.mp4 at the manifest's fps, and
ALL.mp4 — every action side by side with its name burnt in, so one file shows the whole set.

Frames come from the installed sprites (Graphics/Monsters/<name>/), planted on the manifest
anchor exactly as the engine plants them, on the engine's ground colour. That means a wrong
anchor, a trim bug or a popping loop shows up here and not first in the game.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
BG = (58, 62, 52)          # muted ground green-grey, close to the map's average


def load_manifest(name):
    return json.loads((REPO / "Graphics" / "Monsters" / name / "manifest.json").read_text(encoding="utf-8"))


def frame_paths(name, action, direction):
    return sorted((REPO / "Graphics" / "Monsters" / name / action / direction).glob("*.png"))


def anchor_for(manifest, action, direction, index):
    per_frame = manifest.get("frames")
    if per_frame:
        try:
            return per_frame[action][direction][index]["anchor"]
        except (KeyError, IndexError, TypeError):
            pass
    return manifest["anchor_px"]


def composite(manifest, name, action, direction, canvas, ground):
    """Every frame of one action, planted on `ground` (the anchor pixel) in a fixed canvas."""
    out = []
    for i, path in enumerate(frame_paths(name, action, direction)):
        sprite = Image.open(path).convert("RGBA")
        ax, ay = anchor_for(manifest, action, direction, i)
        bg = Image.new("RGBA", canvas, BG + (255,))
        bg.alpha_composite(sprite, (int(ground[0] - ax), int(ground[1] - ay)))
        out.append(np.asarray(bg.convert("RGB"))[:, :, ::-1].copy())   # BGR for cv2
    return out


def label(img, text, scale=0.9):
    cv2.putText(img, text, (14, 34), cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
    cv2.putText(img, text, (14, 34), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 240, 120), 2, cv2.LINE_AA)
    return img


def write(path, frames, fps):
    h, w = frames[0].shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in frames:
        vw.write(f)
    vw.release()
    print(f"  {path.name}  {w}x{h}  {len(frames)} frames @ {fps} fps", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--dir", default="s", help="facing to record (default s = toward the camera)")
    ap.add_argument("--scale", type=float, default=0.5, help="output scale (1.0 = native sprite size)")
    ap.add_argument("--loops", type=int, default=3, help="times to repeat each clip")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    manifest = load_manifest(args.name)
    actions = list(manifest["actions"])
    out_dir = Path(args.out) if args.out else REPO / "generated" / "bosses" / args.name / "preview_video"
    out_dir.mkdir(parents=True, exist_ok=True)

    # one canvas big enough for every frame of every action, anchor at a fixed spot
    max_w = max_h = 0
    max_above = max_below = max_left = max_right = 0
    for action in actions:
        for i, path in enumerate(frame_paths(args.name, action, args.dir)):
            w, h = Image.open(path).size
            ax, ay = anchor_for(manifest, action, args.dir, i)
            max_left = max(max_left, ax); max_right = max(max_right, w - ax)
            max_above = max(max_above, ay); max_below = max(max_below, h - ay)
    canvas = (int(max_left + max_right) + 40, int(max_above + max_below) + 40)
    ground = (max_left + 20, max_above + 20)
    print(f"{args.name}: canvas {canvas}, ground {tuple(round(g) for g in ground)}, actions {actions}")

    per_action = {}
    for action in actions:
        fps = float(manifest["actions"][action].get("fps", 10))
        frames = composite(manifest, args.name, action, args.dir, canvas, ground)
        if args.scale != 1.0:
            frames = [cv2.resize(f, (int(canvas[0] * args.scale), int(canvas[1] * args.scale)),
                                 interpolation=cv2.INTER_AREA) for f in frames]
        per_action[action] = (frames, fps)
        write(out_dir / f"{action}.mp4", [label(f.copy(), f"{action}  {fps:g} fps") for f in frames] * args.loops, fps)

    # ALL.mp4 — every action at once, each looping at its own rate over a common timeline
    grid_fps = 12.0
    seconds = max(len(f) / fps for f, fps in per_action.values()) * args.loops
    total = int(seconds * grid_fps)
    cols = min(3, len(actions))
    rows = math.ceil(len(actions) / cols)
    cw, ch = per_action[actions[0]][0][0].shape[1], per_action[actions[0]][0][0].shape[0]
    grid = []
    for t in range(total):
        tiles = []
        for action in actions:
            frames, fps = per_action[action]
            f = frames[int(t * fps / grid_fps) % len(frames)].copy()
            tiles.append(label(f, action))
        while len(tiles) < rows * cols:
            tiles.append(np.full((ch, cw, 3), BG[::-1], np.uint8))
        grid.append(np.vstack([np.hstack(tiles[r * cols:(r + 1) * cols]) for r in range(rows)]))
    write(out_dir / "ALL.mp4", grid, grid_fps)
    print("done ->", out_dir)


if __name__ == "__main__":
    main()
