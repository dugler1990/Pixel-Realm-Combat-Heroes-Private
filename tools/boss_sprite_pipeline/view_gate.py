"""Generated views of a character, each checked before it goes to TRELLIS. Images only, no 3D.

    python -m tools.boss_sprite_pipeline.view_gate front --input <bare concept> --out <dir> [--draw mask [--margin 0.005]]
    python -m tools.boss_sprite_pipeline.view_gate back  --front <approved front> --out <dir> [--draw mask]
    python -m tools.boss_sprite_pipeline.view_gate side  --front <approved front> --back <approved back> --out <dir>
        [--side left|right]
    [--config <image model json>]: default per view and --draw, see DEFAULT_CONFIG

--draw is how the target outline reaches the model:
- reference (default): it is an image beside the input; the draw lands anywhere and is lined up with the outline
  afterwards (scale to its height, head top on its head top, body centre on its centre, as explode2's
  outline_check did) before it is scored.
- mask: as the interiors: one gpt-image edit with the outline as the mask, the raw return scored against that
  mask, then pasted back inside it (building_interiors._run_edit, paste_back), so the silhouette is the mask's.
  gpt-image fills a mask to within about 3 px (back, 2026-11-08: IoU 0.940 gpt-image-2, 0.941 2.5-flare; the
  reference Leonardo backs scored 0.964-0.976 lined up).

- front: the bare concept dressed in armour (gpt-image). His outline is the concept's, or with --outline his real
  body's (a front silhouette of the 3D body, lined up onto the concept). reference: image 2 is that outline grown
  by --margin; the
  armour must cover it, head and soles left out; only what is missing counts. [rb] draws again asking for armour
  big enough for his chest. mask: his grown outline, head left out, is the mask -- the armour cannot leave skin
  out, but cannot be bigger than the mask either: pauldrons are cut to his shoulders.
- back: the approved front seen from behind; from straight behind his outline is the front's, mirrored.
  reference (Leonardo): image 1 the front, image 2 the mirrored outline. mask (gpt-image): image 1 the mirrored
  outline as a black placeholder, image 2 the front. Scored on IoU and every body band.
- side: drawn by Leonardo from the approved front and back. Its depth has nothing to be checked against in the
  images; the check is only that it is the same size, in the same place, as the front.

Outfit pipeline (outfits/<character>/<outfit>.json, PROCESS_outfit.md): --outfit takes the prompts and settings from
the outfit file ("front", "back", "front_check" cover|match, "margin", "display_joints", "retry_bigger"). Without a
terminal: --no-ask draws once and records it in gate_<view>.json as pending; --retry r|r1|rb|"r <why> @img" draws
again with the same choices as the gate; --accept N accepts attempt N; --dry-run prints the prompt and sends nothing.
"match" (a body, not armour): the draw must fill his outline, scored like a back (IoU and bands), no margin.

At the gate: [enter] accept, [r] draw again, [r1] draw again showing the marked error, [r <why> @img] draw again
with criticism -- as in the interiors, a retry is the same call with the overlay attached, never an edit of the
last attempt. Accept writes the view cut out for TRELLIS (front.png / back.png / side_<left|right>.png) and
gate_<view>.json.
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

LEONARDO = Path(__file__).resolve().parent / "view_gate.json"
GPT_IMAGE = Path(__file__).resolve().parents[1] / "painted_map_pipeline" / "openai.gpt-image-2.json"
DEFAULT_CONFIG = {("front", "reference"): GPT_IMAGE, ("front", "mask"): GPT_IMAGE,
                  ("back", "reference"): LEONARDO, ("back", "mask"): GPT_IMAGE, ("side", "reference"): LEONARDO}

# Heights above the floor, as a share of the figure's height (explode2/outline_check.py). Below the hips a band
# measures one leg: the right half of the figure.
BANDS = [("shoulder", .80), ("chest", .72), ("waist", .60), ("hips", .52), ("thigh", .42), ("knee", .30),
         ("calf", .20), ("ankle", .08)]
# Pass rules. Measured 2026-11-08 on Leonardo draws lined up after the fact (explode2/PROCESS_explode2.md); the
# masked edits land in the target's own frame, so these are a starting point until measured on them.
BACK_MIN_IOU = 0.95       # nano-banana-2.1 back with the outline as image 2: 0.964-0.973
BACK_MAX_BAND = 1.0       # % h
MARGIN = 0.005            # front: his bare outline grown by this share of his height is the outline to cover
HEAD, SOLES = 0.13, 0.02  # front: left out of the score (the head stays bare, the soles stand on the floor);
                          # --draw mask: the head is left out of the mask
FRONT_MAX_MISSING = 0.02  # front, uncovered, head and soles out. Measured on Leonardo fronts: flare_3_extrahigh
                          # 1.37 %; flare_2 2.74, flare_4 3.52, flare_1 4.81, the first fitted front 5.38. A width
                          # check only: depth is not in the image. --draw mask: share of the mask left unpainted
SIDE_MAX_OFF = 0.02       # side: head top, feet and height each within this share of the front's height
MARK_PX = 4               # the overlay's error marks are widened by this many pixels each side to be seen at 1024
UNPAINTED = 12            # back: a pixel of the black placeholder still this dark was not painted (as fill_unpainted)
UNPAINTED_PX = 3          # ... if it is in a patch at least about twice this wide: ink lines are thinner
# --display-joints: joint heights from pose_heights.py (its own venv), drawn as labelled lines on the images sent
POSE_PYTHON = Path(__file__).resolve().parent / ".venv-pose" / "Scripts" / "python.exe"
POSE_SCRIPT = Path(__file__).resolve().parent / "pose_heights.py"
JOINT_COLOURS = {"shoulder": (0, 160, 255), "hip": (255, 0, 255), "knee": (0, 200, 0), "ankle": (255, 140, 0)}
JOINT_MAX_OFF = 1.5       # % of his height, draw minus image 1; judged on hip and knee only -- the shoulder point
JOINT_JUDGED = ("hip", "knee")  # rises with the pauldrons (+3 % h on armoured fronts that keep his shoulders)
JOINT_NOTE = ("The coloured lines labelled SHOULDER, HIP, KNEE and ANKLE across the images mark his joint heights. "
              "Keep his shoulders, hips, knees and ankles exactly on those lines. Do not draw the lines or the labels.")
# Leonardo: reference strength per image -- the inputs are followed; an attached marked copy of the last
# attempt is only a hint of where it went wrong (at HIGH the model copies its own mistake).
INPUT_STRENGTH, ATTACHED_STRENGTH = "HIGH", "LOW"

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
    "front_masked": (
        "Image 1 is a man. Repaint the masked area: dress him in a full suit of steel plate armour worn over a thick "
        "padded gambeson. The armour fills the whole masked area right up to its edge: its outline is the mask's "
        "outline, so no skin shows anywhere in the masked area. Keep his pose, proportions, head, beard, lighting "
        "and the white background exactly as they are."),
    "back": (
        "Draw the man in Image 1 seen from behind. Image 2 is his exact outline from behind: fill it exactly, with "
        "the same pose, size and position, nothing outside it and no gaps. Show his back, hair bun, backplate, the "
        "backs of his arms, legs and heels. Same armour, white background."),
    "back_masked": (
        "Image 1 is a placeholder: the black shape is exactly where the man must be. Repaint the masked area: draw "
        "the man in Image 2 seen from directly behind, filling the black shape completely and exactly, with no black "
        "left. Show his back, hair bun, backplate, the backs of his arms, legs and heels. Same armour as Image 2: "
        "the same design, colours, lighting and painting style. Plain white background."),
    "side": (
        "Draw the man in Image 1 seen from exactly his {side} side, a 90 degree side view facing the {edge} edge of "
        "the image. Image 2 is the same man from behind. Same armour, same height and pose, head and feet at the "
        "same height in the image as in Image 1, full body, orthographic, white background. Every plate stands "
        "clear of his body."),
    "quarter": (
        "Draw the man in Image 1 seen from {view}: a 45 degree three-quarter view, turned toward the {edge} edge of "
        "the image. Image 2 is the same man from behind. Same armour, same height and pose, head and feet at the "
        "same height in the image as in Image 1, full body, orthographic, white background."),
}
# The 3/4 views (`side --side <corner>`): where the camera stands. Each is turned toward the image's left edge
# when the camera is on his left (as his left side view), right edge on his right.
CORNERS = {"front_left": "in front of him and to his left, halfway between his front and his left side",
           "front_right": "in front of him and to his right, halfway between his front and his right side",
           "back_left": "behind him and to his left, halfway between his back and his left side",
           "back_right": "behind him and to his right, halfway between his back and his right side"}
# Images sent before an attachment: an attachment is image FIRST_INDEX.
FIRST_INDEX = {"front": 3, "front_masked": 2, "back": 3, "back_masked": 3, "side": 3, "quarter": 3}
TEXTS = {
    "front": (
        "your previous attempt with its shape error marked: magenta is where his bare outline (the black shape in "
        "image 2) is not covered by the armour",
        "This image shows where your armour leaves his body uncovered. Every part of the black shape in image 2 must "
        "be inside the armour; the armour may always be bigger, never smaller. If it is not covered the image is "
        "not valid and cannot be used, this is the most important directive it takes precedence over any other "
        "contradictory statements earlier in the prompt, thanks."),
    "front_masked": (
        "your previous attempt with its shape error marked: magenta is where the masked area was not filled with "
        "armour",
        "Fill the whole masked area with armour, right up to its edge. If it is not filled the image is not valid "
        "and cannot be used, this is the most important directive it takes precedence over any other "
        "contradictory statements earlier in the prompt, thanks."),
    "back": (
        shape_note("white"),
        "This image represents how you have differed from his outline in image 2, which your drawing must fill "
        "exactly, this shape needs to be pixel perfect relative to that outline, if not the image is not valid and "
        "cannot be used, this is the most important directive it takes precedence over any other contradictory "
        "statements earlier in the prompt, thanks."),
    "back_masked": (
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


def line_up(image: Image.Image, mask: np.ndarray, target: np.ndarray) -> tuple[Image.Image, np.ndarray]:
    """The image and its figure mask moved onto the target's frame: same height (NEAREST for the mask), head top on
    the target's head top, body centre on the target's. For a draw made without a mask, which lands anywhere."""
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


def joint_heights(images: list[Path]) -> dict:
    """pose_heights.py on each image: {path: {joint: {"y", "height_pct", "score"}} or None}."""
    import subprocess
    import tempfile

    if not POSE_PYTHON.exists():
        sys.exit(f"--display-joints needs the pose venv: {POSE_PYTHON} (see pose_heights.py)")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "joints.json"
        subprocess.run([str(POSE_PYTHON), str(POSE_SCRIPT), *map(str, images), "--json", str(out)], check=True,
                       stdout=subprocess.DEVNULL)
        return json.loads(out.read_text(encoding="utf-8"))


def with_joint_lines(src: Path, joints: dict, out: Path) -> Path:
    """`src` with a labelled horizontal line at each joint's height."""
    im = Image.open(src).convert("RGB")
    draw = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("arialbd.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    for name, v in joints.items():
        y = round(v["y"])
        draw.line([(0, y), (im.width, y)], fill=JOINT_COLOURS[name], width=3)
        draw.text((8, y - 26), name.upper(), fill=JOINT_COLOURS[name], font=font)
    im.save(out)
    return out


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


def score_front(target: np.ndarray, has: np.ndarray, masked: bool) -> tuple[dict, np.ndarray]:
    """What must be covered, and how much of it is not; spill is fine. Without a mask: the grown bare outline with
    head and soles left out. --draw mask: the mask itself (the paste cuts any spill)."""
    should = target.copy()
    if not masked:
        top, bottom, height, _ = frame(target)
        should[: int(top + HEAD * height)] = False
        should[int(bottom - SOLES * height):] = False
    s = bands(target, has)
    s["missing"] = float((should & ~has).sum() / max(int(should.sum()), 1))
    s["passed"] = s["missing"] <= FRONT_MAX_MISSING
    s["failing"] = [] if s["passed"] else [f"{'unfilled' if masked else 'uncovered'} {s['missing'] * 100:.2f} %"]
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


def marked(image: Image.Image, missing: np.ndarray, spilled: np.ndarray) -> Image.Image:
    """shape_gate's overlay with the error widened by MARK_PX, so a rim a few pixels wide is visible to the model.
    Only the picture is widened; the scores count the real pixels."""
    from scipy import ndimage

    grow = lambda m: ndimage.binary_dilation(m, iterations=MARK_PX) if m.any() else m  # noqa: E731
    return mark_shape_error(image, grow(missing), grow(spilled))


def evaluate(view: str, raw: Image.Image, target: np.ndarray, tag: Path,
             kept: Image.Image | None = None, sent: tuple = (),
             joints: dict | None = None, exact: np.ndarray | None = None,
             check: str = "cover") -> tuple[dict, list[str], Path, Path | None]:
    """Score one draw. Returns the scores, the lines for the sheet, the sheet and the overlay (None for a side).
    A masked draw (`kept` is its pasted result, shown beside it) is scored on the raw return against the mask that
    was sent, as the interiors score theirs: after the paste there is nothing left to measure. A reference draw is
    lined up with its outline first. `sent`: the images the model was given, shown first on the sheet. `joints`:
    {joint: (row in image 1, draw minus image 1 in % h)} from --display-joints, judged and drawn on the sheet.
    `exact`: front only, his outline with no margin -- the draw marked against it is added as the last panel."""
    shown = [Image.open(p).convert("RGB") for p in sent] or [outline_image(target)]
    if view == "side":
        s = score_side(target, score_mask(raw))
        lines = [f"side: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"head top {s['top'] * 100:+.2f} %  feet {s['feet'] * 100:+.2f} %  height {s['height'] * 100:+.2f} %"
                 "  (of the front's height; red lines: the front's head top and feet)"]
        top, bottom, _, _ = frame(target)
        return s, lines, sheet(shown + [raw], lines, tag.with_name(tag.name + "_sheet.png"),
                               (top, bottom)), None
    drawn = raw
    if kept is None:
        raw, has = line_up(raw, score_mask(raw), target)
    else:
        has = painted(raw)
    if view == "front" and check == "match":
        s = score_back(target, has)
        overlay = marked(raw, target & ~has, has & ~target)
        lines = [f"front (match): {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"IoU {s['iou']:.3f}  missing {s['missing'] * 100:.2f} %  spilled {s['spilled'] * 100:.2f} %"
                 "  (against his outline, no margin)"]
        exact = None
    elif view == "front":
        s, should = score_front(target, has, masked=kept is not None)
        overlay = marked(raw, should & ~has, np.zeros_like(has))
        lines = [f"front: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"mask unfilled {s['missing'] * 100:.2f} %  (raw return; spill is cut by the paste)" if kept
                 is not None else f"bare outline uncovered {s['missing'] * 100:.2f} % (head, soles left out)"]
    else:
        s = score_back(target, has)
        overlay = marked(raw, target & ~has, has & ~target)
        lines = [f"back: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}",
                 f"IoU {s['iou']:.3f}  missing {s['missing'] * 100:.2f} %  spilled {s['spilled'] * 100:.2f} %"
                 + ("  (raw return against the mask)" if kept is not None else "  (lined up with the outline)")]
    lines.append("  ".join(f"{k} {v['diff']:+.2f}" for k, v in s["bands"].items()) + "  (% h, draw minus target)")
    if joints is not None:
        s["joints"] = {k: v[1] for k, v in joints.items()}
        bad = [k for k in JOINT_JUDGED if k in joints and abs(joints[k][1]) > JOINT_MAX_OFF]
        if bad:
            s["passed"] = False
            s["failing"] = s["failing"] + [f"{k} {joints[k][1]:+.1f} % h" for k in bad]
        lines[0] = f"{view}: {'PASS' if s['passed'] else 'FAIL ' + ', '.join(s['failing'])}"
        lines.append("joints, draw minus image 1 (% h): " + "  ".join(f"{k} {v[1]:+.1f}" for k, v in joints.items())
                     + f"  (hip, knee within {JOINT_MAX_OFF}; red lines: image 1's joints)")
    shape_png = tag.with_name(tag.name + "_shape.png")
    overlay.save(shape_png)
    panels = shown + [overlay] + ([kept] if kept is not None else [])
    if exact is not None and view == "front":
        on_exact, has_exact = (raw, has) if kept is not None else line_up(drawn, score_mask(drawn), exact)
        s_exact, should_exact = score_front(exact, has_exact, masked=kept is not None)
        s["exact_missing"] = s_exact["missing"]
        panels.append(marked(on_exact, should_exact & ~has_exact, np.zeros_like(has_exact)))
        lines.append(f"last panel: his exact outline (no margin) uncovered {s_exact['missing'] * 100:.2f} %")
    rows = tuple(round(v[0]) for v in joints.values()) if joints else ()
    return s, lines, sheet(panels, lines, tag.with_name(tag.name + "_sheet.png"), rows), shape_png


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("view", choices=("front", "back", "side"))
    ap.add_argument("--input", type=Path, help="front: the bare concept")
    ap.add_argument("--front", type=Path, help="back, side: the approved armoured front")
    ap.add_argument("--back", type=Path, help="side: the approved back")
    ap.add_argument("--side", choices=("left", "right", *CORNERS), default="left",
                    help="side: left | right, or a 3/4 view: " + " | ".join(CORNERS))
    ap.add_argument("--side-ref", type=Path, action="append", default=[],
                    help="side: an accepted view of him sent too, so this one matches (repeat; e.g. side_left.png)")
    ap.add_argument("--other-side", type=Path, help="side: the side already drawn, sent mirrored so this one matches")
    ap.add_argument("--margin", type=float, default=MARGIN,
                    help="front: the outline to cover is his bare outline grown by this share of his height")
    ap.add_argument("--outline", type=Path,
                    help="front: the outline to cover, if not the concept's own -- his 3D body seen from the front "
                         "(body_silhouette.py)")
    ap.add_argument("--draw", choices=("reference", "mask"), default="reference",
                    help="front, back: the target outline as a reference image (default) or as the edit's mask")
    ap.add_argument("--display-joints", action="store_true",
                    help="draw labelled lines at his shoulder, hip, knee and ankle heights (found on image 1 by "
                         "pose_heights.py) on every image sent, say so in the prompt, and check the draw's joints")
    ap.add_argument("--config", type=Path, help="the image model; default per view and --draw (DEFAULT_CONFIG)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--outfit", type=Path, help="outfit file: prompts and settings (PROCESS_outfit.md)")
    ap.add_argument("--dry-run", action="store_true", help="print the prompt and the images it would send; no call")
    ap.add_argument("--no-ask", action="store_true", help="draw once, record it as pending in gate_<view>.json, exit")
    ap.add_argument("--retry", help="with --no-ask / --dry-run: r | r1 | rb | 'r <why> @img', as at the gate, on the "
                                    "last recorded attempt")
    ap.add_argument("--accept", type=int, help="accept attempt N recorded in gate_<view>.json; no draw")
    a = ap.parse_args()
    check, bigger = "cover", BIGGER
    if a.outfit:
        outfit = json.loads(a.outfit.read_text(encoding="utf-8"))
        for key in ("front", "back", "front_masked", "back_masked", "side", "quarter"):
            if outfit.get(key):
                PROMPTS[key] = outfit[key]
        check = outfit.get("front_check", "cover")
        bigger = outfit.get("retry_bigger") or None
        if "margin" in outfit and a.margin == MARGIN:
            a.margin = float(outfit["margin"])
        a.display_joints = a.display_joints or bool(outfit.get("display_joints"))
    if check == "match":
        a.margin = 0.0
    need = {"front": ["input"], "back": ["front"], "side": ["front", "back"]}[a.view]
    for name in need:
        if getattr(a, name) is None:
            ap.error(f"{a.view} needs --{name}")
    if a.view == "side" and a.draw == "mask":
        ap.error("a side has no outline to use as a mask")
    if a.display_joints and a.draw == "mask":
        ap.error("--display-joints is for --draw reference: a masked edit repaints image 1, lines included")
    a.config = a.config or DEFAULT_CONFIG[(a.view, a.draw)]
    a.out.mkdir(parents=True, exist_ok=True)

    # one gate per side view (left, front_left, ...): an accept closes that view only
    gate_json = a.out / (f"gate_side_{a.side}.json" if a.view == "side" else f"gate_{a.view}.json")
    gate = json.loads(gate_json.read_text(encoding="utf-8")) if gate_json.exists() else {}
    name_of = {"front": "front", "back": "back"}.get(a.view, f"side_{a.side}")
    if a.accept is not None:
        hit = [t for t in gate.get("attempts", []) if t["attempt"] == a.accept]
        if not hit:
            sys.exit(f"no attempt {a.accept} in {gate_json}")
        accept(a, gate, gate_json, Path(hit[0]["draw"]), a.accept, name_of)
        return

    masked = a.draw == "mask"
    exact = None                             # front: his outline with no margin, for the last panel
    mode = a.view + ("_masked" if masked else "")
    prompt = PROMPTS[mode]
    if a.view == "front":
        from scipy import ndimage

        bare = score_mask(Image.open(a.input))
        if a.outline:
            # His real body's outline, moved onto the concept's frame: the armour must fit the body it goes on,
            # and the concept is not that body (barb: the 3D body is 1.2-2.5 % h wider, legs further apart).
            body = score_mask(Image.open(a.outline))
            bare = line_up(Image.fromarray(np.where(body, 0, 255).astype(np.uint8)), body, bare)[1]
        exact = bare.copy()
        top, _, height, _ = frame(bare)
        grow = round(a.margin * height)        # 0: his outline as it is (iterations=0 would grow until it stops)
        target = ndimage.binary_dilation(bare, iterations=grow) if grow > 0 else bare.copy()
        if masked:
            target[: int(top + HEAD * height)] = False
            canvas, refs = Image.open(a.input).convert("RGB"), []
        else:
            outline_image(target).save(a.out / "front_target_outline.png")
            refs = [a.input.resolve(), (a.out / "front_target_outline.png").resolve()]
        name = "front"
    elif a.view == "back":
        target = score_mask(Image.open(a.front))[:, ::-1]
        if masked:
            canvas, refs = outline_image(target), [a.front.resolve()]
        else:
            outline_image(target).save(a.out / "back_target_outline.png")
            refs = [a.front.resolve(), (a.out / "back_target_outline.png").resolve()]
        name = "back"
    else:
        target = score_mask(Image.open(a.front))
        if a.side in CORNERS:
            mode = "quarter"
            prompt = PROMPTS[mode].format(view=CORNERS[a.side], edge=a.side.split("_")[1])
        else:
            prompt = prompt.format(side=a.side, edge=a.side)
        refs, name = [a.front.resolve(), a.back.resolve()], f"side_{a.side}"
        for ref in a.side_ref:
            refs.append(ref.resolve())
            label = ref.stem.replace("side_", "").replace("_", " ")
            prompt += f"\n\nImage {len(refs)} is the same man seen from {'his ' + label + ' side' if label in ('left', 'right') else label}: keep him consistent with it."
        if a.other_side:
            mirrored = a.out / f"side_{a.side}_other_side_mirrored.png"
            Image.open(a.other_side).transpose(Image.FLIP_LEFT_RIGHT).save(mirrored)
            refs.append(mirrored.resolve())
            prompt += (f"\n\nImage {len(refs)} is his other side, mirrored: draw this side to match it, with the same "
                       "armour, size and heights.")
    if masked:
        outline_image(target).save(a.out / f"{a.view}_target_mask.png")
        canvas_path = a.out / f"{a.view}_canvas.png"
        canvas.save(canvas_path)

    ref_joints = None
    if a.display_joints:
        ref_joints = joint_heights([refs[0]])[str(refs[0])]
        if ref_joints is None:
            sys.exit(f"--display-joints: no person found in {refs[0]}")
        refs = [with_joint_lines(p, ref_joints, a.out / f"{a.view}_image{i + 1}_joints.png").resolve()
                for i, p in enumerate(refs)]
        prompt += "\n\n" + JOINT_NOTE
        print("  joints on image 1 (% h above the feet): " + "  ".join(
            f"{k} {v['height_pct']:.1f}" for k, v in ref_joints.items()), file=sys.stderr)

    config = json.loads(a.config.read_text(encoding="utf-8"))
    # A rerun into the same folder carries on numbering: earlier attempts stay on disk.
    done = [int(p.stem.split("_")[2]) for p in a.out.glob(f"{a.view}_attempt_[0-9][0-9]*.png")]
    criticism, attach, attempts, n = "", [], list(gate.get("attempts", [])), max(done, default=0)
    if a.retry:
        criticism, attach = retry_from(a.retry, attempts[-1] if attempts else None, mode, masked, bigger, a.view)
    if a.dry_run:
        extra = refs + [Path(p) for p in attach]
        print(with_criticism(prompt, criticism, attach,
                             first_index=FIRST_INDEX[mode] + (len(refs) - 2 if a.view == "side" else 0)), end="")
        print("\n--- images: " + ", ".join(str(p) for p in extra), file=sys.stderr)
        return
    client = make_image_client(config)
    while True:
        n += 1
        tag = a.out / f"{a.view}_attempt_{n:02d}"
        draw_path = tag.with_suffix(".png")
        sent_prompt = with_criticism(prompt, criticism, attach,
                                     first_index=FIRST_INDEX[mode] + (len(refs) - 2 if a.view == "side" else 0))
        tag.with_name(tag.name + "_prompt.txt").write_text(sent_prompt, encoding="utf-8")
        extra = refs + [Path(p) for p in attach]
        if masked:
            sent(sent_prompt, [("image 1", canvas_path)] + [(f"image {i + 2}", p) for i, p in enumerate(extra)]
                 + [("mask", a.out / f"{a.view}_target_mask.png")])
            # As in the interiors: writes <tag>_input.png, <tag>_mask.png and <tag>_raw.png.
            raw = _run_edit(client, config, sent_prompt, canvas, target, a.out, tag.name, extra_images=extra)
            # The model repaints the whole picture and obeys the mask only roughly: its return is kept inside the
            # mask and image 1 everywhere else.
            kept = paste_back(raw, canvas, target).convert("RGB")
            kept.save(draw_path)
            s, lines, sheet_png, shape_png = evaluate(a.view, raw.convert("RGB"), target, tag, kept, [canvas_path] + refs,
                                                      exact=exact)
        else:
            # Leonardo takes a reference strength per image; gpt-image has none.
            strengths = ([INPUT_STRENGTH] * len(refs) + [ATTACHED_STRENGTH] * len(attach)) \
                if config.get("provider") == "leonardo" else None
            sent(sent_prompt, [(f"image {i + 1}" + (f" {strengths[i]}" if strengths else ""), p)
                               for i, p in enumerate(extra)])
            result = client.generate(sent_prompt, [str(p) for p in extra], str(draw_path), strengths=strengths)
            tag.with_name(tag.name + "_request.json").write_text(json.dumps(
                {"images": [str(p) for p in extra], "strengths": strengths, "result": result}, indent=1,
                default=str), encoding="utf-8")
            joints = None
            if ref_joints is not None and a.view != "side":
                got = joint_heights([draw_path])[str(draw_path)] or {}
                joints = {k: (v["y"], got[k]["height_pct"] - v["height_pct"]) for k, v in ref_joints.items() if k in got}
            s, lines, sheet_png, shape_png = evaluate(a.view, Image.open(draw_path), target, tag, sent=refs,
                                                      joints=joints, exact=exact, check=check)
        attempts.append({"attempt": n, "draw": str(draw_path), "prompt": str(tag.with_name(tag.name + "_prompt.txt")),
                         "images_sent": [str(p) for p in extra], "scores": s,
                         "shape": str(shape_png) if shape_png else None})
        print("\n  " + "\n  ".join(lines) + f"\n  {sheet_png}")
        if a.no_ask:
            gate.update({"view": a.view, "draw": a.draw, "refs": [str(p) for p in refs], "config": str(a.config),
                         "attempts": attempts, "status": "pending", "sheet": str(sheet_png),
                         "front_input": str(a.front) if a.front else None})
            gate_json.write_text(json.dumps(gate, indent=1), encoding="utf-8")
            print(f"  PENDING attempt {n}: --accept {n}, or draw again: --no-ask --retry r|r1|rb|'r <why> @img'")
            return
        show(sheet_png)
        criticism, attach = "", []
        while True:
            raw_answer = ask("\n  [enter] accept   [r] draw again   [r1] draw again showing this draw's shape error"
                             "\n  [rb] draw again asking for bigger armour (not with a mask)"
                             "   [r <why> @img] draw again with criticism   [s] show again   [q] stop", "").strip()
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
                criticism, attach = retry_from(raw_answer, attempts[-1], mode, masked, bigger, a.view)
            except (FileNotFoundError, ValueError) as exc:
                print(f"  {exc}", file=sys.stderr)
            continue
        gate.update({"view": a.view, "draw": a.draw, "refs": [str(p) for p in refs], "config": str(a.config),
                     "attempts": attempts, "front_input": str(a.front) if a.front else None})
        accept(a, gate, gate_json, draw_path, n, name)
        return


def retry_from(answer: str, last: dict | None, mode: str, masked: bool, bigger: str | None, view: str):
    """The gate's retry choices as (criticism, attachments) for the next draw; `last` is the attempt retried."""
    if answer.strip().lower() == "rb":
        if masked:
            raise ValueError("the mask sets the size -- use --margin")
        if not bigger:
            raise ValueError("this outfit has no 'retry_bigger' line")
        return bigger, []
    if answer.strip().lower() == "r":
        return "", []
    if answer[:2].lower() == "r1" and view == "side":
        raise FileNotFoundError("a side has no shape error to show -- use [r <why>]")
    if last is None:
        raise ValueError("no attempt recorded to retry")
    note, directive = TEXTS[mode] if mode in TEXTS else ("", "")
    shape = Path(last["shape"]) if last.get("shape") else None
    return parse_gate_retry(answer, shape, note, directive)


def accept(a, gate: dict, gate_json: Path, draw_path: Path, n: int, name: str) -> None:
    """As the gate's [enter]: the view cut out for TRELLIS (a back also writes the front's), gate_<view>.json."""
    front = a.front or (Path(gate["front_input"]) if gate.get("front_input") else None)
    if a.view == "back" and front is not None:
        figure_cutout(Image.open(front)).save(a.out / "front.png")
    figure_cutout(Image.open(draw_path)).save(a.out / f"{name}.png")
    gate.update({"accepted": n, "status": "accepted"})
    gate_json.write_text(json.dumps(gate, indent=1), encoding="utf-8")
    print(f"  accepted attempt {n}: {a.out / (name + '.png')}")


if __name__ == "__main__":
    main()