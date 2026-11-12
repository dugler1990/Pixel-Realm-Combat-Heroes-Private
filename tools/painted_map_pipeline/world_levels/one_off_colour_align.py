"""Test deterministic colour alignment on an existing world-level attempt.

This does not generate, ingest, accept, or overwrite anything. It learns a conservative
Lab-colour offset from the model's pixels beneath the accepted padding to the accepted pixels
at those same coordinates, applies that offset to the pending part of ``current.png``, and
writes comparison variants beside the attempt.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .checks import join_line

Image.MAX_IMAGE_PIXELS = None


def _latest_attempt(level_root: Path) -> int:
    attempts = sorted(level_root.glob("attempts/attempt_*/current.png"))
    if not attempts:
        raise FileNotFoundError(f"no generated attempts under {level_root}")
    return int(attempts[-1].parent.name.split("_")[1])


def _load(path: Path, mode: str) -> Image.Image:
    if not path.is_file():
        raise FileNotFoundError(path)
    with Image.open(path) as opened:
        return opened.convert(mode)


def _score(
    rgba: np.ndarray, locked_mask: np.ndarray, pending_mask: np.ndarray
) -> dict:
    return join_line(
        Image.fromarray(rgba),
        Image.fromarray(locked_mask.astype(np.uint8) * 255),
        Image.fromarray(pending_mask.astype(np.uint8) * 255),
    )


def _lab_offset(
    raw_rgb: np.ndarray,
    accepted_rgb: np.ndarray,
    locked_mask: np.ndarray,
    *,
    max_samples: int = 200_000,
) -> np.ndarray:
    """Median paired Lab offset, robust to changed texture and individual objects."""
    source = raw_rgb[locked_mask]
    target = accepted_rgb[locked_mask]
    valid = (source.sum(axis=1) > 20) & (target.sum(axis=1) > 20)
    source, target = source[valid], target[valid]
    if len(source) < 1_000:
        raise ValueError(f"only {len(source)} usable overlap pixels; need at least 1000")
    if len(source) > max_samples:
        indices = np.linspace(0, len(source) - 1, max_samples, dtype=np.int64)
        source, target = source[indices], target[indices]

    source_lab = cv2.cvtColor(source.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)
    target_lab = cv2.cvtColor(target.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)
    return np.median(
        target_lab.reshape(-1, 3).astype(np.float32)
        - source_lab.reshape(-1, 3).astype(np.float32),
        axis=0,
    )


def _apply(
    current: np.ndarray,
    accepted_rgb: np.ndarray,
    locked_mask: np.ndarray,
    pending_mask: np.ndarray,
    offset: np.ndarray,
    strength: float,
) -> np.ndarray:
    out = current.copy()
    rgb = out[..., :3]
    painted_pending = pending_mask & (rgb.sum(axis=2) > 20)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    corrected_lab = np.clip(lab + offset * strength, 0, 255).astype(np.uint8)
    corrected_rgb = cv2.cvtColor(corrected_lab, cv2.COLOR_LAB2RGB)
    rgb[painted_pending] = corrected_rgb[painted_pending]
    # Accepted pixels are authoritative and remain byte-identical.
    rgb[locked_mask] = accepted_rgb[locked_mask]
    return out


def _palette_match(
    current: np.ndarray,
    accepted_rgb: np.ndarray,
    locked_mask: np.ndarray,
    pending_mask: np.ndarray,
    strength: float,
) -> np.ndarray:
    """Match the pending area's complete Lab distribution to the accepted padding."""
    out = current.copy()
    rgb = out[..., :3]
    painted_pending = pending_mask & (rgb.sum(axis=2) > 20)
    accepted_painted = locked_mask & (accepted_rgb.sum(axis=2) > 20)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    accepted_lab = cv2.cvtColor(accepted_rgb, cv2.COLOR_RGB2LAB)
    source = lab[painted_pending]
    target = accepted_lab[accepted_painted]
    if len(source) < 1_000 or len(target) < 1_000:
        raise ValueError("not enough painted pixels for full-palette matching")

    quantiles = np.linspace(0.0, 1.0, 513)
    mapped_lab = np.empty_like(lab)
    for channel in range(3):
        source_quantiles = np.quantile(source[:, channel], quantiles)
        target_quantiles = np.quantile(target[:, channel], quantiles)
        unique_source, first = np.unique(source_quantiles, return_index=True)
        lookup = np.interp(
            np.arange(256), unique_source, target_quantiles[first]
        )
        mapped_lab[..., channel] = np.clip(
            lookup[lab[..., channel]], 0, 255
        ).astype(np.uint8)
    mapped_rgb = cv2.cvtColor(mapped_lab, cv2.COLOR_LAB2RGB)
    blended = rgb.astype(np.float32) + (
        mapped_rgb.astype(np.float32) - rgb
    ) * strength
    rgb[painted_pending] = np.clip(
        blended[painted_pending], 0, 255
    ).astype(np.uint8)
    rgb[locked_mask] = accepted_rgb[locked_mask]
    return out


def _paired_delta_lut(
    raw_rgb: np.ndarray,
    accepted_rgb: np.ndarray,
    locked_mask: np.ndarray,
) -> np.ndarray:
    """Learn a nonlinear Lab correction from exact raw/accepted pixel pairs."""
    source = raw_rgb[locked_mask]
    target = accepted_rgb[locked_mask]
    valid = (source.sum(axis=1) > 20) & (target.sum(axis=1) > 20)
    source, target = source[valid], target[valid]
    if len(source) > 250_000:
        indices = np.linspace(0, len(source) - 1, 250_000, dtype=np.int64)
        source, target = source[indices], target[indices]
    source_lab = cv2.cvtColor(source.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)
    target_lab = cv2.cvtColor(target.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)
    source_lab = source_lab.reshape(-1, 3).astype(np.float32)
    target_lab = target_lab.reshape(-1, 3).astype(np.float32)

    keys, inverse = np.unique(
        source_lab.astype(np.int32) // 8, axis=0, return_inverse=True
    )
    representatives, deltas = [], []
    for index in range(len(keys)):
        members = inverse == index
        if int(members.sum()) < 20:
            continue
        representatives.append(np.median(source_lab[members], axis=0))
        deltas.append(
            np.median(target_lab[members] - source_lab[members], axis=0)
        )
    representatives = np.asarray(representatives, dtype=np.float32)
    deltas = np.asarray(deltas, dtype=np.float32)
    if not len(representatives):
        raise ValueError("no populated paired-colour bins")

    values = np.arange(32, dtype=np.float32) * 8 + 4
    lightness, green_red, blue_yellow = np.meshgrid(
        values, values, values, indexing="ij"
    )
    grid = np.stack(
        [lightness, green_red, blue_yellow], axis=-1
    ).reshape(-1, 3)
    lookup = np.empty_like(grid)
    neighbours = min(8, len(representatives))
    for start in range(0, len(grid), 1024):
        cells = grid[start : start + 1024]
        distance = (
            (cells[:, None, :] - representatives[None, :, :]) ** 2
        ).sum(axis=2)
        nearest = np.argpartition(
            distance, neighbours - 1, axis=1
        )[:, :neighbours]
        nearest_distance = np.take_along_axis(distance, nearest, axis=1)
        weight = 1.0 / (nearest_distance + 16.0)
        correction = (
            deltas[nearest] * weight[..., None]
        ).sum(axis=1) / weight.sum(axis=1)[:, None]
        lookup[start : start + len(cells)] = correction
    return lookup


def _apply_paired_lut(
    current: np.ndarray,
    accepted_rgb: np.ndarray,
    locked_mask: np.ndarray,
    pending_mask: np.ndarray,
    lookup: np.ndarray,
    strength: float,
) -> np.ndarray:
    out = current.copy()
    rgb = out[..., :3]
    painted_pending = pending_mask & (rgb.sum(axis=2) > 20)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    quantized = lab.astype(np.int32) // 8
    indices = (
        quantized[..., 0] * 1024
        + quantized[..., 1] * 32
        + quantized[..., 2]
    )
    corrected_lab = np.clip(
        lab.astype(np.float32) + lookup[indices] * strength, 0, 255
    ).astype(np.uint8)
    corrected_rgb = cv2.cvtColor(corrected_lab, cv2.COLOR_LAB2RGB)
    rgb[painted_pending] = corrected_rgb[painted_pending]
    rgb[locked_mask] = accepted_rgb[locked_mask]
    return out


def _comparison(
    variants: list[tuple[str, np.ndarray, dict]],
    generation_mask: np.ndarray,
    output: Path,
) -> None:
    ys, xs = np.where(generation_mask)
    margin = 32
    x0, x1 = max(0, int(xs.min()) - margin), min(generation_mask.shape[1], int(xs.max()) + margin + 1)
    y0, y1 = max(0, int(ys.min()) - margin), min(generation_mask.shape[0], int(ys.max()) + margin + 1)

    panel_width = 900
    label_height = 54
    panels: list[Image.Image] = []
    draw_font = None
    for label, pixels, score in variants:
        crop = Image.fromarray(pixels).crop((x0, y0, x1, y1))
        scale = panel_width / crop.width
        crop = crop.resize(
            (panel_width, max(1, round(crop.height * scale))),
            Image.Resampling.LANCZOS,
        )
        panel = Image.new("RGB", (crop.width, crop.height + label_height), "white")
        panel.paste(crop.convert("RGB"), (0, label_height))
        text = (
            f"{label}   line_step={score.get('line_step')}   "
            f"edge_ratio={score.get('edge_ratio')}   passed={score.get('passed')}"
        )
        ImageDraw.Draw(panel).text((12, 17), text, fill="black", font=draw_font)
        panels.append(panel)

    columns = 2
    rows = (len(panels) + columns - 1) // columns
    cell_height = max(panel.height for panel in panels)
    sheet = Image.new("RGB", (panel_width * columns, cell_height * rows), (32, 32, 32))
    for index, panel in enumerate(panels):
        x = index % columns * panel_width
        y = index // columns * cell_height
        sheet.paste(panel, (x, y))
    sheet.save(output)


def run(root: Path, level_id: str, attempt: int | None, strengths: list[float]) -> dict:
    root = root.resolve()
    level_id = level_id.zfill(2)
    level_root = root / "levels" / level_id
    attempt = attempt or _latest_attempt(level_root)
    attempt_name = f"attempt_{attempt:03d}"
    attempt_dir = level_root / "attempts" / attempt_name
    job_dir = level_root / "jobs" / attempt_name
    canvas_dir = job_dir / "canvas"

    current = np.asarray(_load(attempt_dir / "current.png", "RGBA")).copy()
    raw = np.asarray(_load(attempt_dir / "generated.raw.png", "RGB"))
    accepted = np.asarray(_load(canvas_dir / "locked_overlap.png", "RGB"))
    locked_mask = np.asarray(_load(canvas_dir / "locked_overlap_mask.png", "L")) > 0
    pending_mask = np.asarray(_load(canvas_dir / "pending_mask.png", "L")) > 0
    generation_mask = np.asarray(_load(canvas_dir / "generation_mask.png", "L")) > 0
    if not locked_mask.any():
        raise ValueError(f"level {level_id} attempt {attempt} has no accepted padding")

    offset = _lab_offset(raw, accepted, locked_mask)
    output_dir = attempt_dir / "colour_alignment_test"
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline = _score(current, locked_mask, pending_mask)
    shown: list[tuple[str, np.ndarray, dict]] = [("original", current, baseline)]
    results = []
    for strength in strengths:
        aligned = _apply(
            current, accepted, locked_mask, pending_mask, offset, strength
        )
        score = _score(aligned, locked_mask, pending_mask)
        name = f"lab_offset_{round(strength * 100):03d}.png"
        Image.fromarray(aligned).save(output_dir / name)
        shown.append((f"Lab offset {strength:.0%}", aligned, score))
        results.append(
            {
                "strength": strength,
                "image": str(output_dir / name),
                "join_line": score,
            }
        )

    comparison = output_dir / "offset_comparison_v2.png"
    _comparison(shown, generation_mask, comparison)

    palette_shown: list[tuple[str, np.ndarray, dict]] = [
        ("original", current, baseline)
    ]
    palette_results = []
    for strength in (0.5, 0.75, 1.0):
        aligned = _palette_match(
            current, accepted, locked_mask, pending_mask, strength
        )
        score = _score(aligned, locked_mask, pending_mask)
        name = f"full_palette_{round(strength * 100):03d}.png"
        Image.fromarray(aligned).save(output_dir / name)
        palette_shown.append((f"Full palette {strength:.0%}", aligned, score))
        palette_results.append(
            {
                "strength": strength,
                "image": str(output_dir / name),
                "join_line": score,
            }
        )
    palette_comparison = output_dir / "full_palette_comparison_v2.png"
    _comparison(palette_shown, generation_mask, palette_comparison)

    paired_lookup = _paired_delta_lut(raw, accepted, locked_mask)
    paired_shown: list[tuple[str, np.ndarray, dict]] = [
        ("original", current, baseline)
    ]
    paired_results = []
    for strength in (0.5, 0.75, 1.0, 1.25):
        aligned = _apply_paired_lut(
            current,
            accepted,
            locked_mask,
            pending_mask,
            paired_lookup,
            strength,
        )
        score = _score(aligned, locked_mask, pending_mask)
        name = f"paired_colour_map_{round(strength * 100):03d}.png"
        Image.fromarray(aligned).save(output_dir / name)
        paired_shown.append((f"Paired map {strength:.0%}", aligned, score))
        paired_results.append(
            {
                "strength": strength,
                "image": str(output_dir / name),
                "join_line": score,
            }
        )
    paired_comparison = output_dir / "paired_colour_map_comparison.png"
    _comparison(paired_shown, generation_mask, paired_comparison)

    report = {
        "level_id": level_id,
        "attempt": attempt,
        "source": str(attempt_dir / "current.png"),
        "lab_offset": [round(float(value), 3) for value in offset],
        "baseline_join_line": baseline,
        "offset_variants": results,
        "offset_comparison": str(comparison),
        "full_palette_variants": palette_results,
        "full_palette_comparison": str(palette_comparison),
        "paired_colour_map_variants": paired_results,
        "paired_colour_map_comparison": str(paired_comparison),
        "note": "No source image or run state was modified.",
    }
    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-off deterministic colour alignment test on an existing attempt."
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--level", required=True)
    parser.add_argument("--attempt", type=int)
    parser.add_argument(
        "--strengths",
        default="0.25,0.5,0.75,1.0",
        help="Comma-separated correction strengths (default: 0.25,0.5,0.75,1.0).",
    )
    args = parser.parse_args()
    strengths = [float(value) for value in args.strengths.split(",")]
    if not strengths or any(value < 0 or value > 1 for value in strengths):
        raise ValueError("strengths must be numbers between 0 and 1")
    print(json.dumps(run(args.root, args.level, args.attempt, strengths), indent=2))


if __name__ == "__main__":
    main()
