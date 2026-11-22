"""Joint heights of a person in each image: shoulders, hips, knees, ankles, found by a 2D pose detector (DWPose /
RTMPose body keypoints via rtmlib, CPU, seconds per image). Works on any picture of one person, bare or armoured.

    tools/boss_sprite_pipeline/.venv-pose/Scripts/python.exe tools/boss_sprite_pipeline/pose_heights.py \
        <image> [<image> ...] [--json <out.json>] [--sheet <out.png>] [--arms] [--skeleton <dir>]

Per image and joint: the row in pixels (mean of left and right) and the height above the figure's lowest point as a
% of the figure's height (the figure: everything not near-white), plus the detector's confidence. Prints a table
(differences to the first image when there are several), --json writes it, --sheet draws the joints and their
height lines on every image side by side. --arms adds "_arms" (and "_people": how many found) per image: each arm's angle from straight down
(shoulder to wrist, degrees; an A-pose is about 20-45). --skeleton writes <dir>/<image stem>_skeleton.png: the pose
as a stick figure on white, the same size (a pose to copy without the body).

The venv (gitignored, like .venv-bpy), once:
    python -m venv tools/boss_sprite_pipeline/.venv-pose
    tools/boss_sprite_pipeline/.venv-pose/Scripts/python.exe -m pip install rtmlib onnxruntime
rtmlib downloads its models on first use.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from rtmlib import Body

JOINTS = {"shoulder": (5, 6), "hip": (11, 12), "knee": (13, 14), "ankle": (15, 16)}   # COCO body keypoints
ARMS = {"left": (5, 9), "right": (6, 10)}           # shoulder, wrist (COCO left = the person's left)
LIMBS = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16)]
COLOURS = {"shoulder": (0, 160, 255), "hip": (255, 0, 255), "knee": (0, 200, 0), "ankle": (255, 140, 0)}  # RGB


def figure_rows(img: np.ndarray) -> tuple[int, int]:
    """Top and bottom row of everything not near-white."""
    ys = np.nonzero((img < 240).any(axis=2).any(axis=1))[0]
    return int(ys.min()), int(ys.max())


def best_person(img: np.ndarray, detector: Body):
    """The most confident person's keypoints and scores, or None."""
    kps, scores = detector(img)
    if not len(kps):
        return None
    best = int(np.argmax(scores.mean(1)))
    return kps[best], scores[best]


def arm_angles(k) -> dict:
    """Each arm's angle from straight down, shoulder to wrist, degrees."""
    out = {}
    for side, (s, w) in ARMS.items():
        dx, dy = float(k[w][0] - k[s][0]), float(k[w][1] - k[s][1])
        out[side] = abs(float(np.degrees(np.arctan2(dx, dy))))
    return out


def skeleton(img: np.ndarray, k) -> np.ndarray:
    """The pose as a stick figure on white, the image's size; the head a circle at the nose."""
    out = np.full_like(img, 255)
    th = max(4, img.shape[0] // 90)
    for a, b in LIMBS:
        cv2.line(out, (int(k[a][0]), int(k[a][1])), (int(k[b][0]), int(k[b][1])), (0, 0, 0), th)
    head = int(abs(k[5][0] - k[6][0]) * 0.35)
    cv2.circle(out, (int(k[0][0]), int(k[0][1])), max(head, th * 2), (0, 0, 0), th)
    return out


def joint_heights(img: np.ndarray, detector: Body) -> dict | None:
    """{joint: {"y": row px, "height_pct": above the feet, "score": confidence}} for the most confident person."""
    found = best_person(img, detector)
    if found is None:
        return None
    k, sc = found
    top, bottom = figure_rows(img)
    out = {}
    for name, (a, b) in JOINTS.items():
        y = float((k[a][1] + k[b][1]) / 2)
        out[name] = {"y": y, "height_pct": (bottom - y) / (bottom - top) * 100, "score": float(min(sc[a], sc[b])),
                     "points": [[float(k[i][0]), float(k[i][1])] for i in (a, b)]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--sheet", type=Path)
    ap.add_argument("--arms", action="store_true")
    ap.add_argument("--skeleton", type=Path)
    a = ap.parse_args()
    detector = Body(mode="balanced", backend="onnxruntime", device="cpu")
    results, panels = {}, []
    for p in a.images:
        img = cv2.imread(str(p))
        j = joint_heights(img, detector)
        results[str(p)] = j
        if j is None:
            print(f"  {p.name}: no person found")
            continue
        if a.arms or a.skeleton:
            k = best_person(img, detector)[0]
            if a.arms:
                j["_arms"] = arm_angles(k)
                j["_people"] = int((detector(img)[1].mean(1) > 0.3).sum())      # people found (confident)
                print(f"  {p.name}: arms from straight down: left {j['_arms']['left']:.1f}  right {j['_arms']['right']:.1f}")
            if a.skeleton:
                a.skeleton.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(a.skeleton / f"{p.stem}_skeleton.png"), skeleton(img, k))
        print(f"  {p.name:40s} " + "  ".join(f"{n} {v['height_pct']:5.1f} ({v['score']:.2f})" for n, v in j.items()
                                             if n in JOINTS))
        if a.sheet:
            draw = img.copy()
            for n, v in ((n, v) for n, v in j.items() if n in JOINTS):
                bgr = COLOURS[n][::-1]
                cv2.line(draw, (0, int(v["y"])), (draw.shape[1], int(v["y"])), bgr, 2)
                for x, y in v["points"]:
                    cv2.circle(draw, (int(x), int(y)), 9, bgr, -1)
            panels.append(cv2.resize(draw, (img.shape[1] * 1024 // img.shape[0], 1024)))
    found = [j for j in results.values() if j]
    if len(found) > 1:
        print("  difference to the first (% of height): " + "  ".join(
            f"{n} " + " / ".join(f"{j[n]['height_pct'] - found[0][n]['height_pct']:+.1f}" for j in found[1:])
            for n in JOINTS))
    if a.json:
        a.json.write_text(json.dumps(results, indent=1), encoding="utf-8")
    if a.sheet and panels:
        cv2.imwrite(str(a.sheet), np.hstack(panels))
        print("SHEET", a.sheet)


if __name__ == "__main__":
    main()
