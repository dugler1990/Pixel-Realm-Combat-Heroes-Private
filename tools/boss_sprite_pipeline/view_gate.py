"""Generated views of a character, each checked before it goes to TRELLIS. Images only, no 3D.

    python -m tools.boss_sprite_pipeline.view_gate front --input <bare concept> --out <dir> [--margin 0.005]
    python -m tools.boss_sprite_pipeline.view_gate back  --front <approved front> --out <dir>
    python -m tools.boss_sprite_pipeline.view_gate side  --front <approved front> --back <approved back> --out <dir>
        [--side left|right]

Front and back are drawn the way the interiors are: one gpt-image edit (openai.gpt-image-2.json,
OPENAI_API_KEY) with the target outline as the mask, the raw return scored against that mask, then pasted back
inside it (building_interiors._run_edit, paste_back). The silhouette is the mask's by construction; the check is
whether the model filled it.

- front: image 1 is the bare concept; the mask is his outline grown by --margin, head left out (it stays as
  drawn). He is dressed in armour inside the mask, so the armour covers him and is no bigger than the mask.
- back: image 1 is the front's outline mirrored (from straight behind his outline is the front's, mirrored), a
  black shape on white; image 2 is the approved front. Scored on IoU and every body band.
- side: drawn by Leonardo (view_gate.json) from the approved front and back. Its depth has nothing to be checked
  against in the images; the check is only that it is the same size, in the same place, as the front.

At the gate: [enter] accept, [r] draw again, [r1] draw again showing the marked error, [r <why> @img] draw again
with criticism -- as in the interiors, a retry is the same edit of the same image 1 with the overlay attached,
never an edit of the last attempt. Accept writes the view cut out for TRELLIS (front.png / back.png /
side_<left|right>.png) and gate_<view>.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from tools.painted_map_pipeline.building_interiors import _run_edit, paste_back
from tools.painted_map_pipeline.image_client import make_image_client
from tools.painted_map_pipeline.review_gate import ask, sent, show, with_criticism
from tools.painted_map_pipeline.shape_gate import mark_shape_error, shape_note, shape_scores
from tools.painted_map_pipeline.world_levels.retry import parse_gate_retry
from tools.sprite_assets.cut_sheet import figure_cutout, score_mask

CONFIG = Path(__file__).resolve().parent / "view_gate.json"   # side: Leonardo
EDIT_CONFIG = Path(__file__).resolve().parents[1] / "painted_map_pipeline" / "openai.gpt-image-2.json"

# Heights above the floor, as a share of the figure's height (explode2/outline_check.py). Below the hips a band
# measures one leg: the right half of the figure.
BANDS = [("shoulder", .80), ("chest", .72), ("waist", .60), ("hips", .52), ("thigh", .42), ("knee", .30),
         ("calf", .20), ("ankle", .08)]
# Pass rules. Measured 2026-11-08 on Leonardo draws lined up after the fact (explode2/PROCESS_explode2.md); the
# masked edits land in the target's own frame, so these are a starting point until measured on them.
BACK_MIN_IOU = 0.95       # nano-banana-2.1 back with the outline as image 2: 0.964-0.973
BACK_MAX_BAND = 1.0       # % h
MARGIN = 0.005            # front: the mask is his bare outline grown by this share of his height
HEAD = 0.13               # front: the top of the figure left out of the mask: the head stays as drawn
FRONT_MAX_MISSING = 0.02  # front: share of the mask left unpainted
SIDE_MAX_OFF = 0.02       # side: head top, feet and height each within this share of the front's height
MARK_PX = 4               # the overlay's error marks are widened by this many pixels each side to be seen at 1024
UNPAINTED = 12            # back: a pixel of the black placeholder still this dark was not painted (as fill_unpainted)
UNPAINTED_PX = 3          # ... if it is in a patch at least about twice this wide: ink lines are thinner
# Side, Leonardo: reference strength per image -- the inputs are followed; an attached marked copy of the last
# attempt is only a hint of where it went wrong (at HIGH the model copies its own mistake).
INPUT_STRENGTH, ATTACHED_STRENGTH = "HIGH", "LOW"

PROMPTS = {
    "front": (
        "Image 1 is a man. Repaint the masked area: dress him in a full suit of steel plate armour worn over a thick "
        "padded gambeson. The armour fills the whole masked area right up to its edge: its outline is the mask's "
        "outline, so no skin shows anywhere in the masked area. Keep his pose, proportions, head, beard, lighting "
        "and the white background exactly as they are."),
    "back": (
        "Image 1 is a placeholder: the black shape is exactly where the man must be. Repaint the masked area: draw "
        "the man in Image 2 seen from directly behind, filling the black shape completely and exactly, with no black "
        "left. Show his back, hair bun, backplate, the backs of his arms, legs and heels. Same armour as Image 2: "
        "the same design, colours, lighting and painting style. Plain white background."),
    "side": (
        "Draw the man in Image 1 seen from exactly his {side} side, a 90 degree side view facing the {edge} edge of "
        "the image. Image 2 is the same man from behind. Same armour, same height and pose, head and feet at the "
        "same height in the image as in Image 1, full body, orthographic, white background. Every plate stands "
        "clear of his body."),
}
# Images sent before an attachment: an attachment is image FIRST_INDEX.
FIRST_INDEX = {"front": 2, "back": 3, "side": 3}
TEXTS = {
    "front": (
        "your previous attempt with its shape error marked: magenta is where the masked area was not filled with "
        "armour",
        "Fill the whole masked area with armour, right up to its edge. If it is not filled the image is not valid "
        "and cannot be used, this is the most important directive it takes precedence over any other "
        "contradictory statements earlier in the prompt, thanks."),
    "back": (
        shape_note("white"),
        "This image represents how you have differed from the black shape in image 1, which your drawing must fill "
        "exactly, this shape needs to be pixel perfect relative to that shape, if not the image is not valid and "
        "cannot be used, this is the most important directive it takes precedence over any other contradictory "
        "statements earlier in the prompt, thanks."),
}


def frame(mask: np.ndarray) -> tuple[int, int, int, float]:
    """(top, bottom, height, centre x) of a figure: the centre is the mean x of its top 30 %."""
    ys, xs = np.nonzero(mask)
    top, bottom = int(ys.min()), int(ys.max())
    height = bottom - top
    return top, bottom, height, float(xs[ys < top + 0.3 * height].mean())


def outline_image(mask: np.ndarray) -> Image.Image:
    return Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).convert("RGB")


def painted(raw: Image.Image) -> np.ndarray:
    """The figure the model painted: off the white background, and not the black placeholder left as it was.
    Placeholder left over is a patch; the drawing's own ink lines are as dark but thin, so they are opened away."""
    from scipy import ndimage

    black = np.asarray(raw.convert("RGB")).astype(int).sum(axis=2) <= 3 * UNPAINTED
    return score_mask(raw) & ~ndimage.binary_opening(black, iterations=UNPAINTED_PX)


def bands(target: np.ndarray, has: np.ndarray) -> dict:
    _, bottom, height, cx = frame(target)
    rows = [(name, int(bottom - f * height), slice(int(cx), None) if f < .5 else slice(None)) for name, f in BANDS]
    s = shape_scores(target, has, rows)
    s["bands"] = {k: {kk: round(vv / height * 100, 2) for kk, vv in v.items()} for k, v in s["bands"].items()}
    return s


def score_front(mask: np.ndarray, has: np.ndarray) -> dict:
    """The mask must be filled; spill does not count, the paste cuts it."""
    s = bands(mask, has)
    s["missing"] = float((mask & ~has).sum() / max(int(mask.sum()), 1))
    s["passed"] = s["missing"] <= FRONT_MAX_MISSING
    s["failing"] = [] if s["passed"] else [f"unfilled {s['missing'] * 100:.2f} %"]
    return s


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


def marked(image: Image.Image, missing: np.ndarray, spilled: np.ndarray) -> Image.Image:
    """shape_gate's overlay with the error widened by MARK_PX, so a rim a few pixels wide is visible to the model.
    Only the picture is widened; the scores count the real pixels."""
    from scipy import ndimage

    grow = lambda m: ndimage.binary_dilation(m, iterations=MARK_PX) if m.any() else m  # noqa: E731
    return mark_shape_error(image, grow(missing), grow(spilled))


def evaluate(view: str, raw: Image.Image, target: np.ndarray, tag: Path,
             kept: Image.Image | None = None) -> tuple[dict, list[str], Path, Path | None]:
    """Score one draw. Returns the scores, the lines for the sheet, the sheet and the overlay (None for a side).
    Front and back are scored on the raw return against the mask that was sent, as the interiors score theirs:
    after the paste there is nothing left to measure. `kept` is the pasted result, shown beside it."""
    if view == "side":
        s = score_side(target, score_mask(raw))
        lines = [f"side: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"head top {s['top'] * 100:+.2f} %  feet {s['feet'] * 100:+.2f} %  height {s['height'] * 100:+.2f} %"
                 "  (of the front's height; red lines: the front's head top and feet)"]
        top, bottom, _, _ = frame(target)
        return s, lines, sheet([outline_image(target), raw], lines, tag.with_name(tag.name + "_sheet.png"),
                               (top, bottom)), None
    has = painted(raw)
    if view == "front":
        s = score_front(target, has)
        overlay = marked(raw, target & ~has, np.zeros_like(has))
        lines = [f"front: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"mask unfilled {s['missing'] * 100:.2f} %  (raw return; spill is cut by the paste)"]
    else:
        s = score_back(target, has)
        overlay = marked(raw, target & ~has, has & ~target)
        lines = [f"back: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"IoU {s['iou']:.3f}  missing {s['missing'] * 100:.2f} %  spilled {s['spilled'] * 100:.2f} %"
                 "  (raw return against the mask)"]
    lines.append("  ".join(f"{k} {v['diff']:+.2f}" for k, v in s["bands"].items()) + "  (% h, raw minus mask)")
    shape_png = tag.with_name(tag.name + "_shape.png")
    overlay.save(shape_png)
    panels = [outline_image(target), overlay] + ([kept] if kept is not None else [])
    return s, lines, sheet(panels, lines, tag.with_name(tag.name + "_sheet.png")), shape_png


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("view", choices=("front", "back", "side"))
    ap.add_argument("--input", type=Path, help="front: the bare concept")
    ap.add_argument("--front", type=Path, help="back, side: the approved armoured front")
    ap.add_argument("--back", type=Path, help="side: the approved back")
    ap.add_argument("--side", choices=("left", "right"), default="left")
    ap.add_argument("--margin", type=float, default=MARGIN,
                    help="front: the mask is his bare outline grown by this share of his height")
    ap.add_argument("--config", type=Path, default=CONFIG, help="side: the Leonardo draw")
    ap.add_argument("--edit-config", type=Path, default=EDIT_CONFIG, help="front, back: the masked edit")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    need = {"front": ["input"], "back": ["front"], "side": ["front", "back"]}[a.view]
    for name in need:
        if getattr(a, name) is None:
            ap.error(f"{a.view} needs --{name}")
    a.out.mkdir(parents=True, exist_ok=True)

    prompt = PROMPTS[a.view]
    if a.view == "front":
        from scipy import ndimage

        bare = score_mask(Image.open(a.input))
        top, _, height, _ = frame(bare)
        target = ndimage.binary_dilation(bare, iterations=max(1, round(a.margin * height)))
        target[: int(top + HEAD * height)] = False
        canvas, refs, name = Image.open(a.input).convert("RGB"), [], "front"
    elif a.view == "back":
        target = score_mask(Image.open(a.front))[:, ::-1]
        canvas, refs, name = outline_image(target), [a.front.resolve()], "back"
    else:
        target = score_mask(Image.open(a.front))
        prompt = prompt.format(side=a.side, edge=a.side)
        refs, name = [a.front.resolve(), a.back.resolve()], f"side_{a.side}"
    if a.view != "side":
        outline_image(target).save(a.out / f"{a.view}_target_mask.png")
        canvas_path = a.out / f"{a.view}_canvas.png"
        canvas.save(canvas_path)

    config = json.loads((a.edit_config if a.view != "side" else a.config).read_text(encoding="utf-8"))
    client = make_image_client(config)
    # A rerun into the same folder carries on numbering: earlier attempts stay on disk.
    done = [int(p.stem.split("_")[2]) for p in a.out.glob(f"{a.view}_attempt_[0-9][0-9]*.png")]
    criticism, attach, attempts, n = "", [], [], max(done, default=0)
    while True:
        n += 1
        tag = a.out / f"{a.view}_attempt_{n:02d}"
        sent_prompt = with_criticism(prompt, criticism, attach, first_index=FIRST_INDEX[a.view])
        tag.with_name(tag.name + "_prompt.txt").write_text(sent_prompt, encoding="utf-8")
        extra = refs + [Path(p) for p in attach]
        if a.view == "side":
            draw_path = tag.with_suffix(".png")
            strengths = [INPUT_STRENGTH] * len(refs) + [ATTACHED_STRENGTH] * len(attach)
            sent(sent_prompt, [(f"image {i + 1} {st}", p) for i, (p, st) in enumerate(zip(extra, strengths))])
            result = client.generate(sent_prompt, [str(p) for p in extra], str(draw_path), strengths=strengths)
            tag.with_name(tag.name + "_request.json").write_text(json.dumps(
                {"images": [str(p) for p in extra], "strengths": strengths, "result": result}, indent=1,
                default=str), encoding="utf-8")
            raw = Image.open(draw_path)
            s, lines, sheet_png, shape_png = evaluate(a.view, raw, target, tag)
        else:
            sent(sent_prompt, [("image 1", canvas_path)] + [(f"image {i + 2}", p) for i, p in enumerate(extra)]
                 + [("mask", a.out / f"{a.view}_target_mask.png")])
            # As in the interiors: writes <tag>_input.png, <tag>_mask.png and <tag>_raw.png.
            raw = _run_edit(client, config, sent_prompt, canvas, target, a.out, tag.name, extra_images=extra)
            draw_path = tag.with_suffix(".png")
            # The model repaints the whole picture and obeys the mask only roughly: its return is kept inside the
            # mask and image 1 everywhere else.
            kept = paste_back(raw, canvas, target).convert("RGB")
            kept.save(draw_path)
            s, lines, sheet_png, shape_png = evaluate(a.view, raw.convert("RGB"), target, tag, kept)
        attempts.append({"attempt": n, "draw": str(draw_path), "prompt": str(tag.with_name(tag.name + "_prompt.txt")),
                         "images_sent": [str(p) for p in extra], "scores": s,
                         "shape": str(shape_png) if shape_png else None})
        print("\n  " + "\n  ".join(lines) + f"\n  {sheet_png}")
        show(sheet_png)
        criticism, attach = "", []
        while True:
            raw_answer = ask("\n  [enter] accept   [r] draw again   [r1] draw again showing this draw's shape error"
                             "\n  [r <why> @img] draw again with criticism   [s] show again   [q] stop", "").strip()
            if raw_answer.lower() == "s":
                show(sheet_png)
                continue
            break
        if raw_answer.lower() == "q":
            return
        if raw_answer.lower() == "r":
            continue
        if raw_answer:
            try:
                if raw_answer[:2].lower() == "r1" and a.view == "side":
                    raise FileNotFoundError("a side has no shape error to show -- use [r <why>]")
                note, directive = TEXTS[a.view] if a.view in TEXTS else ("", "")
                criticism, attach = parse_gate_retry(raw_answer, shape_png, note, directive)
            except FileNotFoundError as exc:
                print(f"  {exc}", file=sys.stderr)
            continue
        if a.view == "back":
            figure_cutout(Image.open(a.front)).save(a.out / "front.png")
        figure_cutout(Image.open(draw_path)).save(a.out / f"{name}.png")
        (a.out / f"gate_{a.view}.json").write_text(json.dumps(
            {"view": a.view, "refs": [str(p) for p in refs], "config": str(a.edit_config if a.view != "side"
                                                                            else a.config),
             "attempts": attempts, "accepted": n}, indent=1), encoding="utf-8")
        print(f"  accepted attempt {n}: {a.out / (name + '.png')}")
        return


if __name__ == "__main__":
    main()
