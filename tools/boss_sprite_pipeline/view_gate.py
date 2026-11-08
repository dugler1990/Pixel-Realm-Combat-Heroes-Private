"""A generated view of a character, checked against the outline it must have, before it goes to TRELLIS.

    python -m tools.boss_sprite_pipeline.view_gate front --input <bare concept> --body <base_rigged.glb> --out <dir>
    python -m tools.boss_sprite_pipeline.view_gate back  --input <approved front> --out <dir> [--body <base_rigged.glb>]
        [--config tools/boss_sprite_pipeline/view_gate.json]

Two targets, one scoring path. Both views send two images, the second being the outline to hit:
- front (dress the bare concept in armour): his body's outline (body_silhouette.py on the rigged base,
  lined up with the concept's figure), grown by MARGIN. The armour must cover it, head and soles left
  out (the head stays bare, the soles stand on the floor); reaching past it is fine. Only what is
  missing counts, and the overlay marks only that.
- back (the approved front seen from behind): the front's outline mirrored left to right -- from straight
  behind, that is his outline. Missing and spilled both count. With --body, his body from behind is
  printed as a cover check, not a pass.
Sides have no outline to derive and are not handled; none goes to the pod unchecked.

Each draw is lined up with the target as explode2's outline_check did (scale to its height, head top on its
head top, body centre on its centre), scored per band, and marked with shape_gate's overlay on the lined-up
draw. [r1] redraws with that overlay and this view's own note and directive, through the same retry parser and
console gate as the interiors. Images are made through Leonardo's API (view_gate.json; quantity 1: the client
keeps only the first image of a batch). Accept writes <out>/<view>.png (figure_cutout, ready for TRELLIS) and
<out>/gate.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tools.boss_sprite_pipeline import bpy_python
from tools.painted_map_pipeline.image_client import make_image_client
from tools.painted_map_pipeline.review_gate import ask, sent, show, with_criticism
from tools.painted_map_pipeline.shape_gate import mark_shape_error, shape_note, shape_scores
from tools.painted_map_pipeline.world_levels.retry import parse_gate_retry
from tools.sprite_assets.cut_sheet import figure_cutout, score_mask

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "view_gate.json"

# Heights above the floor, as a share of the figure's height (explode2/outline_check.py). Below the hips a band
# measures one leg: the right half of the figure.
BANDS = [("shoulder", .80), ("chest", .72), ("waist", .60), ("hips", .52), ("thigh", .42), ("knee", .30),
         ("calf", .20), ("ankle", .08)]
MARGIN = 0.005            # front: plate must clear his body by this share of his height
HEAD, SOLES = 0.13, 0.02  # front: left out of the score (bare head; feet on the floor)
# Pass rules, from the 2026-11-08 measurements (explode2/PROCESS_explode2.md):
BACK_MIN_IOU = 0.95       # nano-banana-2.1 back with the outline as image 2: 0.964; gpt-image backs 0.919, 0.916
BACK_MAX_BAND = 1.0       # % h; that back: +0.41 at worst; the gpt backs -1.22 (shoulder), -1.72 (hips)
FRONT_MAX_MISSING = 0.01  # the front in use leaves 6.67 % of his outline uncovered and 32 % of his skin
                          # outside it in 3D: failing it is correct

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
}
FRONT_SHAPE_NOTE = (
    "your previous attempt with its shape error marked: magenta is where his body (the black shape in image 2) is "
    "not covered by the armour")
FRONT_SHAPE_DIRECTIVE = (
    "This image shows where your armour leaves his body uncovered. Every part of the black shape in image 2 must be "
    "inside the armour; the armour may always be bigger, never smaller. If it is not covered the image is not valid "
    "and cannot be used, this is the most important directive it takes precedence over any other contradictory "
    "statements earlier in the prompt, thanks.")
BACK_SHAPE_DIRECTIVE = (
    "This image represents how you have differed from his outline in image 2, which your drawing must fill exactly, "
    "this shape needs to be pixel perfect relative to that outline, if not the image is not valid and cannot be "
    "used, this is the most important directive it takes precedence over any other contradictory statements "
    "earlier in the prompt, thanks.")
TEXTS = {"front": (FRONT_SHAPE_NOTE, FRONT_SHAPE_DIRECTIVE), "back": (shape_note("white"), BACK_SHAPE_DIRECTIVE)}


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


def outline_png(mask: np.ndarray, path: Path) -> Path:
    """A mask as a black shape on white: the outline sent as image 2."""
    Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).convert("RGB").save(path)
    return path


def body_outline(body_glb: Path, view: str, out: Path) -> np.ndarray:
    """His body's outline from `view`, rendered by body_silhouette.py through the Blender venv."""
    subprocess.run([str(bpy_python(HERE)), str(HERE / "body_silhouette.py"), str(body_glb.resolve()),
                    str(out.resolve()), view], check=True, capture_output=True)
    return score_mask(Image.open(out / f"body_{view}.png"))


def grown(mask: np.ndarray, pixels: int) -> np.ndarray:
    from scipy import ndimage

    return ndimage.binary_dilation(mask, iterations=max(1, pixels))


def band_rows(target: np.ndarray):
    top, bottom, height, cx = frame(target)
    return [(name, int(bottom - f * height), slice(int(cx), None) if f < .5 else slice(None)) for name, f in BANDS]


def score(view: str, target: np.ndarray, has: np.ndarray) -> tuple[dict, np.ndarray]:
    """Scores of a lined-up draw. Front: `should` is the target with head and soles left out, only missing counts.
    Back: the whole target, IoU and every band."""
    top, bottom, height, _ = frame(target)
    should = target.copy()
    if view == "front":
        should[: int(top + HEAD * height)] = False
        should[int(bottom - SOLES * height):] = False
    s = shape_scores(should, has, band_rows(target))
    s["bands"] = {k: {kk: round(vv / height * 100, 2) for kk, vv in v.items()} for k, v in s["bands"].items()}
    if view == "front":
        s["passed"] = s["missing"] <= FRONT_MAX_MISSING
        s["failing"] = [] if s["passed"] else [f"missing {s['missing'] * 100:.2f} %"]
    else:
        bad = [k for k, v in s["bands"].items() if abs(v["diff"]) > BACK_MAX_BAND]
        s["passed"] = s["iou"] >= BACK_MIN_IOU and not bad
        s["failing"] = ([] if s["iou"] >= BACK_MIN_IOU else [f"IoU {s['iou']:.3f}"]) + [
            f"{k} {s['bands'][k]['diff']:+.2f} % h" for k in bad]
    return s, should


def sheet(target: np.ndarray, drawn: Image.Image, overlay: Image.Image, lines: list[str], path: Path) -> Path:
    """target | lined-up draw | overlay, with the scores written above."""
    w, h = target.shape[::-1]
    out = Image.new("RGB", (w * 3, h + 24 * len(lines) + 8), (25, 25, 28))
    for i, im in enumerate((Image.fromarray(np.where(target, 0, 255).astype(np.uint8)).convert("RGB"), drawn, overlay)):
        out.paste(im, (i * w, 24 * len(lines) + 8))
    draw = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for i, line in enumerate(lines):
        draw.text((8, 4 + 24 * i), line, fill=(255, 255, 255), font=font)
    out.save(path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("view", choices=("front", "back"))
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--body", type=Path)
    ap.add_argument("--config", type=Path, default=CONFIG)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    if a.view == "front" and not a.body:
        ap.error("front needs --body: the target is his body's outline")
    a.out.mkdir(parents=True, exist_ok=True)
    source = Image.open(a.input)
    source_mask = score_mask(source)

    if a.view == "front":
        body = body_outline(a.body, "front", a.out)
        _, body = line_up(Image.new("RGB", body.shape[::-1]), body, source_mask)   # into the concept's frame
        target = grown(body, round(MARGIN * frame(body)[2]))
    else:
        target = source_mask[:, ::-1]
    image2 = outline_png(target, a.out / "target_outline.png")
    cover_back = None
    if a.view == "back" and a.body:
        cover_back = body_outline(a.body, "back", a.out)

    config = json.loads(a.config.read_text(encoding="utf-8"))
    client = make_image_client(config)
    base_prompt, inputs = PROMPTS[a.view], [a.input.resolve(), image2.resolve()]
    criticism, attach, attempts, n = "", [], [], 0
    while True:
        n += 1
        tag = a.out / f"attempt_{n:02d}"
        prompt = with_criticism(base_prompt, criticism, attach, first_index=3)
        images = inputs + [Path(p) for p in attach]
        tag.with_name(tag.name + "_prompt.txt").write_text(prompt, encoding="utf-8")
        sent(prompt, [(f"image {i + 1}", p) for i, p in enumerate(images)])
        draw_path = tag.with_suffix(".png")
        client.generate(prompt, [str(p) for p in images], str(draw_path))
        drawn = Image.open(draw_path)
        lined, has = line_up(drawn, score_mask(drawn), target)
        s, should = score(a.view, target, has)
        if cover_back is not None:
            _, back_body = line_up(Image.new("RGB", cover_back.shape[::-1]), cover_back, target)
            uncovered = grown(back_body, round(MARGIN * frame(back_body)[2])) & ~has
            s["cover_back"] = float(uncovered.sum() / max(int(back_body.sum()), 1))
        overlay = mark_shape_error(lined, should | has, has) if a.view == "front" else mark_shape_error(lined, should, has)
        shape_png = tag.with_name(tag.name + "_shape.png")
        overlay.save(shape_png)
        lines = [f"{a.view} attempt {n}: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"IoU {s['iou']:.3f}  missing {s['missing'] * 100:.2f} %  spilled {s['spilled'] * 100:.2f} %"
                 + (f"  his back uncovered {s['cover_back'] * 100:.2f} %" if "cover_back" in s else ""),
                 "  ".join(f"{k} {v['diff']:+.2f}" for k, v in s["bands"].items()) + "  (% h, draw minus target)"]
        sheet_png = sheet(target, lined, overlay, lines, tag.with_name(tag.name + "_sheet.png"))
        attempts.append({"attempt": n, "draw": str(draw_path), "prompt": str(tag.with_name(tag.name + "_prompt.txt")),
                         "images_sent": [str(p) for p in images], "scores": s, "shape": str(shape_png)})
        print("\n  " + "\n  ".join(lines) + f"\n  {sheet_png}")
        show(sheet_png)
        criticism, attach = "", []
        while True:
            raw = ask("\n  [enter] accept   [r] draw again   [r1] redraw showing this draw's shape error"
                      "\n  [r <why> @img] redraw with criticism   [s] show again   [q] stop", "").strip()
            if raw.lower() == "s":
                show(sheet_png)
                continue
            break
        if raw.lower() == "q":
            return
        if raw.lower() == "r":
            continue
        if raw:
            try:
                criticism, attach = parse_gate_retry(raw, shape_png, *TEXTS[a.view])
            except FileNotFoundError as exc:
                print(f"  {exc}", file=sys.stderr)
            continue
        figure_cutout(drawn).save(a.out / f"{a.view}.png")
        (a.out / "gate.json").write_text(json.dumps(
            {"view": a.view, "input": str(a.input), "body": str(a.body) if a.body else None, "config": str(a.config),
             "target": str(image2), "attempts": attempts, "accepted": n}, indent=1), encoding="utf-8")
        print(f"  accepted attempt {n}: {a.out / (a.view + '.png')}")
        return


if __name__ == "__main__":
    main()
