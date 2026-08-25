"""Automatic tests on a generated attempt.

Each check returns a number and a verdict, and nothing else: what goes back to the model on a
retry is only ever what a person types, so a check never speaks for itself.

The geometric checks restate what the renderers already enforce. ``padding_seam`` is the one
that exists only here, because the failure it catches is the one nobody automated: a visible
line where the finished padding meets the new art.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

# A join is invisible when the edge energy sitting on it is no stronger than the edge energy
# a little way to either side -- texture either continues or it does not. Measured as a ratio
# so it does not care how detailed the terrain happens to be.
SEAM_EDGE_RATIO = 1.5
# Mean per-channel step across the join, in 0-255 units. Calibrated against joins judged by
# eye: ones that read as continuous measure 0.8-1.6, ones with a line measure 9.3-42.
SEAM_COLOUR_STEP = 5.0
BAND_PX = 4
CONTROL_OFFSET_PX = 10


def _grad(rgb: np.ndarray) -> np.ndarray:
    grey = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    return cv2.magnitude(
        cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3)
    )


def _bands(locked: np.ndarray, pending: np.ndarray) -> dict[str, np.ndarray]:
    """Thin strips hugging the join, and control strips set back from it on both sides."""
    from_locked = cv2.distanceTransform((~locked).astype(np.uint8), cv2.DIST_L2, 3)
    from_pending = cv2.distanceTransform((~pending).astype(np.uint8), cv2.DIST_L2, 3)
    return {
        "new_edge": pending & (from_locked <= BAND_PX),
        "old_edge": locked & (from_pending <= BAND_PX),
        "new_control": pending
        & (from_locked > CONTROL_OFFSET_PX)
        & (from_locked <= CONTROL_OFFSET_PX + 2 * BAND_PX),
        "old_control": locked
        & (from_pending > CONTROL_OFFSET_PX)
        & (from_pending <= CONTROL_OFFSET_PX + 2 * BAND_PX),
    }


def padding_seam(image: Image.Image, locked_mask: Image.Image, pending_mask: Image.Image) -> dict:
    """How visible the line is where the padding meets the new art.

    Two independent ways for a join to show: a ridge of edge energy lying along it, and a flat
    step in colour across it. Either alone is enough to read as a border, so both are reported
    and the check fails on whichever trips.
    """
    rgb = np.asarray(image.convert("RGB"))
    locked = np.asarray(locked_mask.convert("L")) > 0
    pending = np.asarray(pending_mask.convert("L")) > 0
    if not locked.any() or not pending.any():
        return {
            "name": "padding_seam",
            "skipped": "this level has no padding",
            "passed": True,
        }

    bands = _bands(locked, pending)
    if not all(band.any() for band in bands.values()):
        return {"name": "padding_seam", "skipped": "join too thin to measure", "passed": True}

    grad = _grad(rgb)
    join = grad[bands["new_edge"] | bands["old_edge"]].mean()
    control = grad[bands["new_control"] | bands["old_control"]].mean()
    # Floor the denominator: flat terrain either side of a hard line is the most visible seam
    # there is, and dividing by its near-zero edge energy would score it as perfect. Real
    # painted ground sits well above this, so the floor only bites on the degenerate case.
    ratio = float(join / max(control, 1.0))

    step = float(
        np.abs(
            rgb[bands["new_edge"]].mean(axis=0).astype(float)
            - rgb[bands["old_edge"]].mean(axis=0).astype(float)
        ).mean()
    )

    edge_failed = ratio > SEAM_EDGE_RATIO
    step_failed = step > SEAM_COLOUR_STEP
    return {
        "name": "padding_seam",
        "edge_ratio": round(ratio, 3),
        "edge_ratio_limit": SEAM_EDGE_RATIO,
        "colour_step": round(step, 2),
        "colour_step_limit": SEAM_COLOUR_STEP,
        "passed": not (edge_failed or step_failed),
    }


# What the overlay's two colours mean, and what to do about them. Kept next to the code that
# draws it so the wording and the colours cannot drift apart, and reused verbatim as the note
# sent back to the model when the overlay is attached to a retry.
FOOTPRINT_OVERLAY_NOTE = (
    "your previous attempt with its shape error marked: magenta is where you left it black "
    "and it should be painted, cyan is where you painted and it should be black"
)
# The standing instruction that goes with it. Kept here rather than at the call site so the
# picture, the words describing it and the demand made of it stay one thing.
FOOTPRINT_OVERLAY_DIRECTIVE = (
    "This image represents how you have differed from the black canvas you are meant to copy "
    "in the image you were told to upscale, this shape needs to be pixel perfect relative to "
    "the reference image, if not the image is not valid and cannot be used, this is the most "
    "important directive it takes precedence over any other contradictory statements earlier "
    "in the prompt, thanks."
)
OVERLAY_MISSING = (255, 60, 255)
OVERLAY_SPILLED = (60, 255, 255)
OVERLAY_STRENGTH = 0.55


def footprint_overlay(image: Image.Image, generation_mask: Image.Image) -> Image.Image:
    """The generation with its footprint error painted on.

    An IoU is a single number for an error that is always a rim, and where the rim sits is the
    part worth seeing. Marked with the same content threshold ``footprint_iou`` counts with, so
    the picture and the score cannot disagree.
    """
    from .land_fit import CONTENT_LUMA_THRESHOLD

    rgb = image.convert("RGB")
    drawn = np.asarray(rgb).sum(axis=2) > CONTENT_LUMA_THRESHOLD
    mask = np.asarray(generation_mask.convert("L")) > 0
    marked = np.asarray(rgb).copy()
    marked[mask & ~drawn] = OVERLAY_MISSING
    marked[drawn & ~mask] = OVERLAY_SPILLED
    return Image.blend(rgb, Image.fromarray(marked), OVERLAY_STRENGTH)


def footprint(image: Image.Image, generation_mask: Image.Image, *, minimum: float) -> dict:
    """Whether the paint landed inside the shape it was given."""
    from .land_fit import CONTENT_LUMA_THRESHOLD, footprint_iou

    value = float(footprint_iou(image, generation_mask))
    drawn = np.asarray(image.convert("RGB")).sum(axis=2) > CONTENT_LUMA_THRESHOLD
    mask = np.asarray(generation_mask.convert("L")) > 0
    missing = int((mask & ~drawn).sum())
    # What the IoU becomes if the spill is simply cut off at the polygon. A cut removes
    # overshoot for free and cannot fill shortfall, so this is exactly how much of the polygon
    # got painted -- and it separates the two failures the raw IoU blurs together. A return
    # that spilled badly but covered the shape is one composite away from perfect; one that
    # left holes is not fixable at all and has to be redrawn.
    cut = 1.0 - missing / int(mask.sum()) if mask.any() else 0.0
    return {
        "name": "footprint",
        "iou": round(value, 4),
        "cut_iou": round(cut, 4),
        "minimum": minimum,
        # Split the error into its two directions: they are fixed by different instructions.
        "missing_px": missing,
        "spilled_px": int((drawn & ~mask).sum()),
        "passed": value >= minimum,
    }


# Any pixel of the polygon left unpainted. Zero by default, because a level that is even
# slightly smaller than its polygon is not usable: the gap is copied verbatim into whichever
# neighbour inherits that ground as padding, which lands a band of black in the middle of the
# next level's input. That happened -- 28,153 unpainted pixels on one level put an 11-row black
# bar into its neighbour, and no amount of re-placing repairs it. Nothing downstream can invent
# the missing paint, so the only remedy is another generation.
MAX_MISSING_PX = 0


def coverage(image: Image.Image, generation_mask: Image.Image, *, maximum: int = MAX_MISSING_PX) -> dict:
    """Whether the paint reaches every pixel of the polygon.

    Deliberately separate from ``footprint``. That reports a single IoU, in which spill and
    shortfall cancel each other out and a level can score 0.9998 while still being too small.
    They need different answers: spill is trimmed by a cut, shortfall needs regenerating.
    """
    from .land_fit import CONTENT_LUMA_THRESHOLD

    drawn = np.asarray(image.convert("RGB")).sum(axis=2) > CONTENT_LUMA_THRESHOLD
    mask = np.asarray(generation_mask.convert("L")) > 0
    missing = int((mask & ~drawn).sum())
    total = int(mask.sum())
    return {
        "name": "coverage",
        "missing_px": missing,
        "missing_frac": round(missing / total, 6) if total else 0.0,
        "maximum": maximum,
        "passed": missing <= maximum,
    }


def full_bleed(image: Image.Image) -> dict:
    """Whether any black is left at all -- an outline exists to check against."""
    from .land_fit import is_full_bleed

    bled = bool(is_full_bleed(image))
    return {"name": "full_bleed", "painted_edge_to_edge": bled, "passed": not bled}


def _latest_attempt(level_root: Path) -> int | None:
    attempts = sorted(level_root.glob("attempts/attempt_*/"))
    return int(attempts[-1].name.split("_")[1]) if attempts else None


def run_checks(root: str | Path, level_id: str, attempt: int | None = None) -> dict[str, Any]:
    """Every check for one attempt, against the job snapshot it was generated from."""
    from .job_builder import canvas_asset
    from .package_builder import level_paths
    from .state_store import read_json

    root_path = Path(root).resolve()
    level_id = level_id.zfill(2)
    paths = level_paths(root_path, level_id)
    if attempt is None:
        attempt = _latest_attempt(paths["root"])
    if attempt is None:
        return {"level_id": level_id, "error": "this level has no attempts yet"}

    attempt_dir = paths["root"] / "attempts" / f"attempt_{attempt:03d}"
    job_dir = paths["root"] / "jobs" / f"attempt_{attempt:03d}"

    # Score current.png, never the raw. The raw is what the model returned and no setting
    # changes it, so scoring it would leave every number identical after a warp. current.png
    # is the version the chosen settings actually produced, which is the thing being judged.
    current_path = attempt_dir / "current.png"
    if not current_path.is_file():
        return {"level_id": level_id, "attempt": attempt, "error": f"no result at {attempt_dir}"}
    with Image.open(current_path) as opened:
        current = opened.convert("RGBA")

    mask = Image.open(canvas_asset(job_dir, "generation_mask"))
    # Both renderers build their result on a blank canvas after rejecting a wrong-sized return,
    # so this holds by construction. An assert rather than a branch: it is the cheaper half of
    # what a branch would do, and if a future renderer breaks the invariant this says so
    # instead of letting the checks fail on a shape mismatch further down.
    assert current.size == mask.size, f"result is {current.size}, canvas is {mask.size}"

    config = read_json(root_path / "config.resolved.json")
    minimum = float(config.get("execution", {}).get("rescale_below_iou") or 0.9)

    # A rim error is far easier to act on as a picture than as a number, and this is also the
    # image the review loop can attach to a retry.
    overlay_path = attempt_dir / "footprint_overlay.png"
    footprint_overlay(current, mask).save(overlay_path)

    results = [
        full_bleed(current),
        footprint(current, mask, minimum=minimum),
        coverage(current, mask),
        padding_seam(
            current,
            Image.open(canvas_asset(job_dir, "locked_mask")),
            Image.open(canvas_asset(job_dir, "pending_mask")),
        ),
    ]
    failed = [item for item in results if not item["passed"]]
    return {
        "level_id": level_id,
        "attempt": attempt,
        "passed": not failed,
        "checks": results,
        "overlay_path": str(overlay_path),
    }


def format_report(report: dict[str, Any]) -> str:
    """One line per check, for a terminal."""
    if report.get("error"):
        return f"level {report.get('level_id')}: {report['error']}"
    lines = [f"level {report['level_id']} attempt {report['attempt']}:"]
    for item in report["checks"]:
        if item.get("skipped"):
            lines.append(f"  --  {item['name']}: skipped ({item['skipped']})")
            continue
        detail = ", ".join(
            f"{key}={value}"
            for key, value in item.items()
            if key not in {"name", "passed"}
        )
        lines.append(f"  {'ok' if item['passed'] else 'FAIL'}  {item['name']}: {detail}")
        # A footprint that fails only because it spilled is one composite from perfect, and
        # that is not obvious from two numbers sitting side by side.
        if item["name"] == "coverage" and not item["passed"]:
            lines.append(
                f"      the generation is SMALLER than its polygon by {item['missing_px']:,} px. "
                f"Nothing can fill that in - regenerate."
            )
        if item["name"] == "footprint" and item.get("cut_iou", 0) - item["iou"] > 0.01:
            lines.append(
                f"      the miss is spill, not holes: cutting to the polygon gives "
                f"{item['cut_iou']:.4f} with no warping -- press c"
            )
    if report.get("overlay_path"):
        lines += ["", "  shape error drawn on the generation:", f"    {report['overlay_path']}"]
    return "\n".join(lines)
