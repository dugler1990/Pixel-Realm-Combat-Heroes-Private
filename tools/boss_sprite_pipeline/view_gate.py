"""Generated views of a character, each checked before it goes to TRELLIS. Images only, no 3D.

    python -m tools.boss_sprite_pipeline.view_gate front --input <bare concept> --out <dir>
    python -m tools.boss_sprite_pipeline.view_gate back  --front <approved front> --out <dir>
    python -m tools.boss_sprite_pipeline.view_gate side  --front <approved front> --back <approved back> --out <dir>
        [--side left|right] [--config tools/boss_sprite_pipeline/view_gate.json]

- front: the bare concept dressed in armour. Image 2 is the bare outline grown by MARGIN; the armour must
  cover it (head and soles left out: the head stays bare, the soles stand on the floor). Only what is missing
  counts and only that is marked.
- back: the approved front seen from behind. From straight behind his outline is the front's mirrored, so
  that is image 2 and the target: IoU and every body band. Missing and spilled are both marked.
- side: drawn from the approved front and back. Its depth has nothing to be checked against in the images;
  the check is only that it is the same size, in the same place, as the front (head top and feet rows).

Each draw is lined up with its target (scale to its height, head top on its head top, body centre on its
centre, as explode2's outline_check did), scored, and marked with shape_gate's overlay. At the gate: [enter]
accept, [r] draw again, [r1] redraw showing the marked error, [rb] redraw asking for armour realistically big
enough to cover his large chest, [r <why> @img] redraw with criticism. Images come from Leonardo's API
(view_gate.json; quantity 1: the client keeps only the first image of a batch). Accept writes the view cut out
for TRELLIS (front.png / back.png / side_<left|right>.png) and gate_<view>.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tools.painted_map_pipeline.image_client import make_image_client
from tools.painted_map_pipeline.review_gate import ask, sent, show, with_criticism
from tools.painted_map_pipeline.shape_gate import mark_shape_error, shape_note, shape_scores
from tools.painted_map_pipeline.world_levels.retry import parse_gate_retry
from tools.sprite_assets.cut_sheet import figure_cutout, score_mask

CONFIG = Path(__file__).resolve().parent / "view_gate.json"

# Heights above the floor, as a share of the figure's height (explode2/outline_check.py). Below the hips a band
# measures one leg: the right half of the figure.
BANDS = [("shoulder", .80), ("chest", .72), ("waist", .60), ("hips", .52), ("thigh", .42), ("knee", .30),
         ("calf", .20), ("ankle", .08)]
# Pass rules, from the 2026-11-08 measurements (explode2/PROCESS_explode2.md):
BACK_MIN_IOU = 0.95       # nano-banana-2.1 back with the outline as image 2: 0.964-0.973; gpt-image backs 0.919, 0.916
BACK_MAX_BAND = 1.0       # % h; those backs: +0.41 at worst; the gpt backs -1.22 (shoulder), -1.72 (hips)
MARGIN = 0.005            # front: plate must clear the bare outline by this share of his height
HEAD, SOLES = 0.13, 0.02  # front: left out of the score
FRONT_MAX_MISSING = 0.02  # uncovered, head and soles out: flare_3_extrahigh 1.37 %; flare_2 2.74, flare_4 3.52,
                          # flare_1 4.81, the first fitted front 5.38. A width check only: depth is not in the image
SIDE_MAX_OFF = 0.02       # side: head top, feet and height each within this share of the front's height

BIGGER = ("Make the armour realistically big enough to cover his large chest, shoulders and arms: thick plate "
          "standing well clear of his muscles everywhere, never tight to the body.")
PROMPTS = {
    "front": (
        "Dress the man in Image 1 in a full suit of steel plate armour worn over a thick padded gambeson. Keep his "
        "pose, proportions, head, beard, framing, camera and white background identical. The armour sits over his "
        "body: every plate stands clear of the skin by about a finger's width, so the armoured outline is larger "
        "than his bare outline everywhere, including shoulders, arms, chest, waist, hips, legs and feet. If unsure, "
        "make the armour slightly too big rather than too tight. No skin visible except the head. Image 2 is the "
        "outline his armour must cover: every part of the black shape is inside the armour; the armour may reach "
        "past it."),
    "back": (
        "Draw the man in Image 1 seen from behind. Image 2 is his exact outline from behind: fill it exactly, with "
        "the same pose, size and position, nothing outside it and no gaps. Show his back, hair bun, backplate, the "
        "backs of his arms, legs and heels. Same armour, white background."),
    "side": (
        "Draw the man in Image 1 seen from exactly his {side} side, a 90 degree side view facing the {edge} edge of "
        "the image. Image 2 is the same man from behind. Same armour, same height and pose, head and feet at the "
        "same height in the image as in Image 1, full body, orthographic, white background. Every plate stands "
        "clear of his body."),
}
TEXTS = {
    "front": (
        "your previous attempt with its shape error marked: magenta is where his bare outline (the black shape in "
        "image 2) is not covered by the armour",
        "This image shows where your armour leaves his body uncovered. Every part of the black shape in image 2 must "
        "be inside the armour; the armour may always be bigger, never smaller. If it is not covered the image is "
        "not valid and cannot be used, this is the most important directive it takes precedence over any other "
        "contradictory statements earlier in the prompt, thanks."),
    "back": (
        shape_note("white"),
        "This image represents how you have differed from his outline in image 2, which your drawing must fill "
        "exactly, this shape needs to be pixel perfect relative to that outline, if not the image is not valid and "
        "cannot be used, this is the most important directive it takes precedence over any other contradictory "
        "statements earlier in the prompt, thanks."),
}


def frame(mask: np.ndarray) -> tuple[int, int, int, float]:
    """(top, bottom, height, centre x) of a figure: the centre is the mean x of its top 30 %."""
    ys, xs = np.nonzero(mask)
    top, bottom = int(ys.min()), int(ys.max())
    height = bottom - top
    return top, bottom, height, float(xs[ys < top + 0.3 * height].mean())


def line_up(image: Image.Image, mask: np.ndarray, target: np.ndarray) -> tuple[Image.Image, np.ndarray]:
    """The image and its figure mask moved onto the target's frame: same height (NEAREST for the mask), head top on
    the target's head top, body centre on the target's."""
    top, _, height, cx = frame(mask)
    t_top, _, t_height, t_cx = frame(target)
    s = t_height / height
    size = (round(mask.shape[1] * s), round(mask.shape[0] * s))
    at = (round(t_cx - cx * s), round(t_top - top * s))
    out_mask = Image.new("L", target.shape[::-1], 0)
    out_mask.paste(Image.fromarray((mask * 255).astype(np.uint8)).resize(size, Image.NEAREST), at)
    out_image = Image.new("RGB", target.shape[::-1], (255, 255, 255))
    out_image.paste(image.convert("RGB").resize(size, Image.BILINEAR), at)
    return out_image, np.asarray(out_mask) > 127


def outline_image(mask: np.ndarray) -> Image.Image:
    return Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).convert("RGB")


def bands(target: np.ndarray, has: np.ndarray) -> dict:
    _, bottom, height, cx = frame(target)
    rows = [(name, int(bottom - f * height), slice(int(cx), None) if f < .5 else slice(None)) for name, f in BANDS]
    s = shape_scores(target, has, rows)
    s["bands"] = {k: {kk: round(vv / height * 100, 2) for kk, vv in v.items()} for k, v in s["bands"].items()}
    return s


def score_front(target: np.ndarray, has: np.ndarray) -> tuple[dict, np.ndarray]:
    """The bare outline (grown) with head and soles left out must be covered; spill is fine."""
    top, bottom, height, _ = frame(target)
    should = target.copy()
    should[: int(top + HEAD * height)] = False
    should[int(bottom - SOLES * height):] = False
    s = bands(target, has)
    s["missing"] = float((should & ~has).sum() / max(int(should.sum()), 1))
    s["passed"] = s["missing"] <= FRONT_MAX_MISSING
    s["failing"] = [] if s["passed"] else [f"uncovered {s['missing'] * 100:.2f} %"]
    return s, should


def score_back(target: np.ndarray, has: np.ndarray) -> dict:
    s = bands(target, has)
    bad = [k for k, v in s["bands"].items() if abs(v["diff"]) > BACK_MAX_BAND]
    s["passed"] = s["iou"] >= BACK_MIN_IOU and not bad
    s["failing"] = ([] if s["iou"] >= BACK_MIN_IOU else [f"IoU {s['iou']:.3f}"]) + [
        f"{k} {s['bands'][k]['diff']:+.2f} % h" for k in bad]
    return s


def score_side(front: np.ndarray, side: np.ndarray) -> dict:
    """Same size, same place: head top, feet and height against the front's, as shares of its height."""
    f_top, f_bottom, f_height, _ = frame(front)
    s_top, s_bottom, s_height, _ = frame(side)
    s = {"top": (s_top - f_top) / f_height, "feet": (s_bottom - f_bottom) / f_height,
         "height": (s_height - f_height) / f_height}
    s["failing"] = [f"{k} {v * 100:+.2f} %" for k, v in s.items() if abs(v) > SIDE_MAX_OFF]
    s["passed"] = not s["failing"]
    return s


def sheet(panels: list[Image.Image], lines: list[str], path: Path, rows: tuple = ()) -> Path:
    """The panels side by side, the scores written above, and `rows` drawn across every panel."""
    w, h = panels[0].size
    head = 24 * len(lines) + 8
    out = Image.new("RGB", (w * len(panels), h + head), (25, 25, 28))
    for i, im in enumerate(panels):
        out.paste(im.convert("RGB").resize((w, h)), (i * w, head))
    draw = ImageDraw.Draw(out)
    for y in rows:
        draw.line([(0, head + y), (out.width, head + y)], fill=(255, 40, 40), width=2)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for i, line in enumerate(lines):
        draw.text((8, 4 + 24 * i), line, fill=(255, 255, 255), font=font)
    out.save(path)
    return path


def evaluate(view: str, drawn: Image.Image, target: np.ndarray, tag: Path) -> tuple[dict, list[str], Path, Path]:
    """Score one draw. Returns the scores, the lines for the sheet, the sheet and the overlay (None for a side)."""
    if view == "side":
        s = score_side(target, score_mask(drawn))
        lines = [f"side: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"head top {s['top'] * 100:+.2f} %  feet {s['feet'] * 100:+.2f} %  height {s['height'] * 100:+.2f} %"
                 "  (of the front's height; red lines: the front's head top and feet)"]
        top, bottom, _, _ = frame(target)
        return s, lines, sheet([outline_image(target), drawn], lines, tag.with_name(tag.name + "_sheet.png"),
                               (top, bottom)), None
    lined, has = line_up(drawn, score_mask(drawn), target)
    if view == "front":
        s, should = score_front(target, has)
        overlay = mark_shape_error(lined, should | has, has)
        lines = [f"front: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"bare outline uncovered {s['missing'] * 100:.2f} % (head, soles left out)"]
    else:
        s = score_back(target, has)
        overlay = mark_shape_error(lined, target, has)
        lines = [f"back: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"IoU {s['iou']:.3f}  missing {s['missing'] * 100:.2f} %  spilled {s['spilled'] * 100:.2f} %"]
    lines.append("  ".join(f"{k} {v['diff']:+.2f}" for k, v in s["bands"].items()) + "  (% h, draw minus target)")
    shape_png = tag.with_name(tag.name + "_shape.png")
    overlay.save(shape_png)
    return s, lines, sheet([outline_image(target), lined, overlay], lines, tag.with_name(tag.name + "_sheet.png")), shape_png


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("view", choices=("front", "back", "side"))
    ap.add_argument("--input", type=Path, help="front: the bare concept")
    ap.add_argument("--front", type=Path, help="back, side: the approved armoured front")
    ap.add_argument("--back", type=Path, help="side: the approved back")
    ap.add_argument("--side", choices=("left", "right"), default="left")
    ap.add_argument("--config", type=Path, default=CONFIG)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    need = {"front": ["input"], "back": ["front"], "side": ["front", "back"]}[a.view]
    for name in need:
        if getattr(a, name) is None:
            ap.error(f"{a.view} needs --{name}")
    a.out.mkdir(parents=True, exist_ok=True)

    prompt = PROMPTS[a.view]
    if a.view == "front":
        bare = score_mask(Image.open(a.input))
        from scipy import ndimage
        target = ndimage.binary_dilation(bare, iterations=max(1, round(MARGIN * frame(bare)[2])))
        image1, name = a.input, "front"
    elif a.view == "back":
        target = score_mask(Image.open(a.front))[:, ::-1]
        image1, name = a.front, "back"
    else:
        target = score_mask(Image.open(a.front))
        prompt = prompt.format(side=a.side, edge=a.side)
        image1, name = a.front, f"side_{a.side}"
    if a.view == "side":
        image2 = a.back
    else:
        image2 = a.out / f"{a.view}_target_outline.png"
        outline_image(target).save(image2)

    client = make_image_client(json.loads(a.config.read_text(encoding="utf-8")))
    inputs = [image1.resolve(), Path(image2).resolve()]
    criticism, attach, attempts, n = "", [], [], 0
    while True:
        n += 1
        tag = a.out / f"{a.view}_attempt_{n:02d}"
        sent_prompt = with_criticism(prompt, criticism, attach, first_index=3)
        images = inputs + [Path(p) for p in attach]
        tag.with_name(tag.name + "_prompt.txt").write_text(sent_prompt, encoding="utf-8")
        sent(sent_prompt, [(f"image {i + 1}", p) for i, p in enumerate(images)])
        draw_path = tag.with_suffix(".png")
        client.generate(sent_prompt, [str(p) for p in images], str(draw_path))
        drawn = Image.open(draw_path)
        s, lines, sheet_png, shape_png = evaluate(a.view, drawn, target, tag)
        attempts.append({"attempt": n, "draw": str(draw_path), "prompt": str(tag.with_name(tag.name + "_prompt.txt")),
                         "images_sent": [str(p) for p in images], "scores": s,
                         "shape": str(shape_png) if shape_png else None})
        print("\n  " + "\n  ".join(lines) + f"\n  {sheet_png}")
        show(sheet_png)
        criticism, attach = "", []
        while True:
            raw = ask("\n  [enter] accept   [r] draw again   [r1] redraw showing this draw's shape error"
                      "\n  [rb] redraw asking for bigger armour   [r <why> @img] redraw with criticism"
                      "   [s] show again   [q] stop", "").strip()
            if raw.lower() == "s":
                show(sheet_png)
                continue
            break
        if raw.lower() == "q":
            return
        if raw.lower() == "r":
            continue
        if raw.lower() == "rb":
            criticism = BIGGER
            continue
        if raw:
            try:
                if raw[:2].lower() == "r1" and a.view == "side":
                    raise FileNotFoundError("a side has no shape error to show -- use [r <why>]")
                note, directive = TEXTS[a.view] if a.view in TEXTS else ("", "")
                criticism, attach = parse_gate_retry(raw, shape_png, note, directive)
            except FileNotFoundError as exc:
                print(f"  {exc}", file=sys.stderr)
            continue
        if a.view == "back":
            figure_cutout(Image.open(a.front)).save(a.out / "front.png")
        figure_cutout(drawn).save(a.out / f"{name}.png")
        (a.out / f"gate_{a.view}.json").write_text(json.dumps(
            {"view": a.view, "image1": str(image1), "image2": str(image2), "config": str(a.config),
             "attempts": attempts, "accepted": n}, indent=1), encoding="utf-8")
        print(f"  accepted attempt {n}: {a.out / (name + '.png')}")
        return


if __name__ == "__main__":
    main()
