"""Polish one rendered part of a boss with gpt-image-2: generate -> look -> accept / retry.

Same loop as world_levels/review_run.py, and the same retry-with-context as
world_levels/job_builder._with_retry_context: every rejected attempt goes back as a further
image with the note you typed about it, so a retry does not start cold. Reuses
tools.painted_map_pipeline.openai_api.edit_image -- nothing image-API related lives here.
No mask is sent: the model edits the real pixels.

    py -3.12 tools/boss_sprite_pipeline/part_polish.py \
        --render generated/bosses/demon/head_views/gpt2_front_sculpt/head_front_flat_PADDED_2048.png \
        --out generated/bosses/demon/part_polish/gpt2_front_sculpt/face_2048

After each generation the output opens in the viewer, then:

    Enter          accept  (writes <out>/ACCEPTED.txt with the attempt path)
    r <why>        reject with a reason; retry with this and every earlier rejected attempt attached
    r1 [why]       same, plus a red change-overlay of the last attempt (what moved vs the render)
    e [N] <what>   edit attempt N's output directly (default: the last one): it becomes image 1
                   and the prompt is "<what>. Change nothing else."  -- for small fixes like lips
    p <prompt>     replace the base prompt and retry (rejection history still attached)
    q              quit
    (--continue opens the menu on the last attempt instead of making a new one)

Each attempt writes <out>/attempt_N/{input.png, prompt.txt, output.png, AB.png, check.json}
and, once rejected, rejection.txt. Needs OPENAI_API_KEY in the environment.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from tools.painted_map_pipeline.openai_api import edit_image  # noqa: E402

GREY = (128, 128, 128)
RETRY_HISTORY = 1          # job_builder uses 4; here 2+ extra images tank alignment (IoU 0.998 -> 0.81)
RETRY_THUMBNAIL = 1024     # older attempts are context, not the thing being corrected
_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth")

DEFAULT_PROMPT = (
    "Produce the final colour texture for this demon boss head for a stylised indie game. It "
    "will be rendered as a large sprite, so it must read strongly and look cool at a glance: "
    "hand-painted texture style, bold readable shapes, punchy saturated colour, strong value "
    "contrast, clean confident edges - not photoreal, no pores or fine noise. Image 1 is the "
    "current flat unlit texture render; image 2 is the same head with neutral lighting so the "
    "true shape of every feature is visible. Take image 1 well beyond its current state: "
    "painterly skin with deliberate colour variation (warmer on the cheekbones and brow, cooler "
    "and darker in the hollows), each tooth and the gums cleanly defined with a painted lip edge "
    "around the mouth, horn ridges as clean sculpted bands, a nose that clearly reads as a nose "
    "with dark nostrils and a lighter bridge, and hero eyes - luminous molten-ember irises with "
    "a near-white core, saturated orange, deep crimson rim, one crisp specular glint, and a "
    "warm glow bleeding onto the skin around the sockets. Be bold; make it look like a strong "
    "concept artist painted it. "
    "This is a texture, not a new picture: the geometry is fixed. Every feature stays at exactly "
    "the same position, size and outline as in image 1, the view and framing are identical, and "
    "the style stays flat and unlit (no cast shadows or scene lighting painted in). Keep the "
    "plain grey background untouched."
)


def _attempts(out: Path) -> list[Path]:
    return sorted((p for p in out.glob("attempt_*") if p.is_dir()), key=lambda p: int(p.name.split("_")[1]))


def _next_attempt(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    n = 1 + max((int(p.name.split("_")[1]) for p in _attempts(out)), default=0)
    d = out / f"attempt_{n}"
    d.mkdir()
    return d


def _rejection_note(attempt_dir: Path) -> str:
    note = attempt_dir / "rejection.txt"
    return note.read_text(encoding="utf-8").strip() if note.is_file() else ""


def prepare_input(render: Path, attempt: Path) -> tuple[Path, np.ndarray]:
    rgba = Image.open(render).convert("RGBA")
    alpha = np.asarray(rgba)[:, :, 3] > 8
    bg = Image.new("RGBA", rgba.size, GREY + (255,))
    bg.alpha_composite(rgba)
    inp = attempt / "input.png"
    bg.convert("RGB").save(inp)
    return inp, alpha


def with_retry_context(out: Path, attempt: Path, prompt: str, inputs: list[Path]) -> tuple[str, list[Path]]:
    """Straight port of job_builder._with_retry_context: append every rejected attempt (last
    RETRY_HISTORY) as a further image, each with what was wrong with it; older ones thumbnailed."""
    history = [(p, _rejection_note(p)) for p in _attempts(out) if p != attempt]
    history = [h for h in history if h[1] and (h[0] / "output.png").is_file()][-RETRY_HISTORY:]
    if not history:
        return prompt, inputs
    images = list(inputs)
    lines = [prompt.rstrip(), ""]
    if len(history) > 1:
        lines.append(f"You have tried this {len(history)} times and each attempt was rejected.")
    for position, (path, note) in enumerate(history):
        ordinal = _ORDINALS[min(position, len(_ORDINALS) - 1)]
        with Image.open(path / "output.png") as opened:
            image = opened.convert("RGB")
            if path is not history[-1][0]:
                image.thumbnail((RETRY_THUMBNAIL, RETRY_THUMBNAIL))
            ctx = attempt / f"context_{path.name}.png"
            image.save(ctx)
        images.append(ctx)
        lines.append(f"Image {len(images)} is your {ordinal} attempt. It was rejected because:")
        lines.append(note)
    lines += [
        "",
        "Try again from the same inputs, using your most recent attempt as the starting",
        "point, and fix everything named above - including what was wrong with the earlier",
        "attempts. Everything else about it was right; change nothing else.",
    ]
    return "\n".join(lines), images


OVERLAY_NOTE = ("shows in red every area of your last attempt that differs from the original "
                "render. Those red areas must match the original exactly, except where the "
                "instructions asked for a change.")


def change_overlay(inp: Path, out: Path, path: Path, tol: int = 40) -> Path:
    """Red-tint every pixel of `out` that differs from `inp` by more than `tol` (as review_run's
    shape overlay: a picture of the error, not a description of it)."""
    a = np.asarray(Image.open(inp).convert("RGB")).astype(int)
    b = np.asarray(Image.open(out).convert("RGB")).astype(int)
    moved = np.abs(a - b).max(axis=2) > tol
    over = b.astype(np.float32)
    over[moved] = over[moved] * 0.35 + np.array([255, 0, 0]) * 0.65
    Image.fromarray(over.astype(np.uint8)).save(path)
    return path


def silhouette_iou(output: Path, alpha: np.ndarray, tol: int = 18) -> dict:
    rgb = np.asarray(Image.open(output).convert("RGB")).astype(int)
    non_grey = np.abs(rgb - np.array(GREY)).max(axis=2) > tol
    inter = (non_grey & alpha).sum()
    union = (non_grey | alpha).sum()
    return {"iou": float(inter / max(union, 1)), "added_px": int((non_grey & ~alpha).sum()),
            "lost_px": int((~non_grey & alpha).sum())}


def write_ab(inp: Path, out: Path, path: Path) -> None:
    a, b = Image.open(inp).convert("RGB"), Image.open(out).convert("RGB")
    sheet = Image.new("RGB", (a.width + b.width, max(a.height, b.height)))
    sheet.paste(a, (0, 0)); sheet.paste(b, (a.width, 0)); sheet.save(path)


def generate(render: Path, out_root: Path, prompt: str, quality: str, ref: Path | None = None,
             base: Path | None = None, overlay: tuple[Path, str] | None = None,
             retrying: bool = False) -> tuple[Path, dict]:
    """base: an earlier attempt's output.png to edit directly (image 1) instead of the render.
    overlay: (image, note) attached one-shot after the rejection history, as review_run's r1."""
    attempt = _next_attempt(out_root)
    inp, alpha = prepare_input(render, attempt)          # alpha: silhouette of the ORIGINAL render
    if base:
        Image.open(base).convert("RGB").save(inp)        # image 1 = previous output, same framing
    w, h = Image.open(inp).size
    inputs = [inp]
    if ref:
        r = attempt / "ref_lit.png"
        Image.open(ref).convert("RGB").save(r)
        inputs.append(r)
    if retrying:   # as orchestrate: history only rides along on an explicit retry, never on a fresh run
        prompt, inputs = with_retry_context(out_root, attempt, prompt, inputs)
    if overlay:
        path, note = overlay
        ov = attempt / "attached_overlay.png"
        Image.open(path).convert("RGB").save(ov)
        inputs.append(ov)
        prompt = prompt.rstrip() + "\n\nImage " + str(len(inputs)) + " " + note
    prompt = prompt.encode("ascii", "ignore").decode("ascii")
    (attempt / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    out = attempt / "output.png"
    info = edit_image(prompt=prompt, input_images=inputs, mask=None, output_path=out,
                      width=w, height=h, config={"quality": quality, "config_source": "part_polish"})
    check = silhouette_iou(out, alpha)
    check["usage"] = info.get("usage")
    check["context_images"] = [str(p) for p in inputs[1:]]
    (attempt / "check.json").write_text(json.dumps(check, indent=1), encoding="utf-8")
    write_ab(inp, out, attempt / "AB.png")
    return attempt, check


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--render", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--quality", default="high")
    ap.add_argument("--ref", type=Path, default=None, help="lit render from the same camera, sent as image 2 for shape")
    ap.add_argument("--open-with", default="code", help="Command to open the image ('' to just print the path)")
    ap.add_argument("--continue", dest="cont", action="store_true", help="Open the menu on the last attempt instead of generating")
    args = ap.parse_args()

    prompt = args.prompt
    base: Path | None = None
    overlay: tuple[Path, str] | None = None
    retrying = False
    resume = args.cont and bool(_attempts(args.out))
    while True:
        if resume:
            attempt = _attempts(args.out)[-1]
            check = json.loads((attempt / "check.json").read_text(encoding="utf-8"))
            check.setdefault("context_images", [])
            resume = False
        else:
            attempt, check = generate(args.render, args.out, prompt, args.quality, args.ref, base, overlay, retrying)
        base, overlay, retrying = None, None, False
        ab = attempt / "AB.png"
        print(f"\n{attempt}\n  silhouette iou={check['iou']:.3f}  added={check['added_px']}  lost={check['lost_px']}"
              f"  context={len(check['context_images'])}")
        if args.open_with:
            subprocess.Popen([args.open_with, "-r", str(ab)], shell=True)   # do not wait on the viewer
        else:
            print(f"  {ab}")
        while True:
            line = input("    [Enter]=accept  r <why>=reject+retry  r1 [why]=retry+overlay  "
                         "e [N] <what>=edit attempt N  p <prompt>=new base prompt  q=quit > ").strip()
            if line == "":
                (args.out / "ACCEPTED.txt").write_text(str(attempt) + "\n", encoding="utf-8")
                print(f"accepted {attempt}")
                return 0
            if line.lower() == "q":
                return 1
            if line.lower().startswith("p "):
                prompt = line[2:].strip()
                break
            if line.lower().startswith("e"):
                parts = line[1:].strip().split(None, 1)
                if parts and parts[0].isdigit():
                    target = args.out / f"attempt_{parts[0]}"
                    what = parts[1] if len(parts) > 1 else ""
                else:
                    target = attempt
                    what = " ".join(parts)
                if not what or not (target / "output.png").is_file():
                    print("    e [N] <what to change>   (attempt N must exist)")
                    continue
                base = target / "output.png"
                prompt = (f"Image 1 is the current version of the demon head. {what}. Change absolutely "
                          "nothing else: same colours, same shapes, same framing, same background.")
                break
            if line.lower().startswith("r1"):
                why = line[2:].strip() or "areas outside the requested changes were altered"
                ov = change_overlay(attempt / "input.png", attempt / "output.png", attempt / "change_overlay.png")
                overlay = (ov, OVERLAY_NOTE)
                (attempt / "rejection.txt").write_text(why + "\n", encoding="utf-8")
                retrying = True
                break
            if line.lower().startswith("r"):
                why = line[1:].strip()
                if why:
                    (attempt / "rejection.txt").write_text(why + "\n", encoding="utf-8")
                    retrying = True
                break
            print("    ?")


if __name__ == "__main__":
    raise SystemExit(main())
