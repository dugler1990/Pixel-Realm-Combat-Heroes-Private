"""Padding bakeoff on an existing world-level job snapshot.

Reuses one frozen job (same input / pad / locator / masks) so the only variables are
prompt and quality. Each variant is generated, then placed and
hard-pasted exactly as ingest does. Does not touch run.json or create pipeline attempts.

Needs OPENAI_API_KEY in the environment (same as the pipeline).

    python -m tools.painted_map_pipeline.world_levels.bakeoff_padding \
      generated/world_levels/sunspine_01 --level 02 --from-attempt 3

Judge ``normalized.png`` (after paste). ``generated.png`` is the pre-paste draw.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from ..image_client import ImageClientError, make_image_client
from ..openai_api import OpenAIApiError
from .config import load_config
from .frames import Frame
from .job_builder import canvas_asset
from .package_builder import level_paths
from .renderers import FrameRenderer, PlaceContext, load_image
from .state_store import read_json

Image.MAX_IMAGE_PIXELS = None

HERE = Path(__file__).resolve().parent
WORLD_PROMPT = HERE / "prompts" / "frostreach_07_carry_outward.txt"

# OpenAI list rates reviewed mid-2026. Log tokens either way; USD is an estimate.
USD_PER_MILLION = {
    "text_input": 5.0,
    "image_input": 8.0,
    "image_output": 30.0,
}


def _variants(current_prompt: str, world_prompt: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "world_prompt",
            "label": "world prompt, quality=medium, no fidelity",
            "prompt": world_prompt,
            "quality": "medium",
            "input_fidelity": None,
        },
        {
            "id": "fidelity_high",
            "label": "current prompt, quality=medium",
            "prompt": current_prompt,
            "quality": "medium",
            "input_fidelity": None,
        },
        {
            "id": "world_prompt_fidelity_high",
            "label": "world prompt, quality=medium",
            "prompt": world_prompt,
            "quality": "medium",
            "input_fidelity": None,
        },
        {
            "id": "quality_high",
            "label": "world prompt, quality=high (expensive), no fidelity",
            "prompt": world_prompt,
            "quality": "high",
            "input_fidelity": None,
        },
    ]


def _estimate_usd(usage: dict[str, Any] | None) -> float | None:
    if not usage:
        return None
    details = usage.get("input_tokens_details") or {}
    text = float(details.get("text_tokens") or 0)
    image_in = float(details.get("image_tokens") or 0)
    out_details = usage.get("output_tokens_details") or {}
    image_out = float(out_details.get("image_tokens") or usage.get("output_tokens") or 0)
    return (
        text * USD_PER_MILLION["text_input"]
        + image_in * USD_PER_MILLION["image_input"]
        + image_out * USD_PER_MILLION["image_output"]
    ) / 1_000_000.0


def _open_images(paths: list[Path]) -> None:
    existing = [str(path) for path in paths if path.is_file()]
    if not existing:
        return
    try:
        subprocess.run(["code", "-r", *existing], check=False)
        return
    except FileNotFoundError:
        pass
    for path in existing:
        try:
            subprocess.run(["xdg-open", path], check=False)
        except FileNotFoundError:
            print("open these yourself:")
            for item in existing:
                print(f"  {item}")
            return


def _normalize(
    generated: Path, job: dict[str, Any], job_dir: Path, config
) -> tuple[Image.Image, dict]:
    renderer = FrameRenderer()
    generation_mask = load_image(canvas_asset(job_dir, "generation_mask"), "L")
    locked_mask = load_image(canvas_asset(job_dir, "locked_mask"), "L")
    locked_pixels = load_image(canvas_asset(job_dir, "locked_pixels"))
    with Image.open(generated) as opened:
        raw = opened.convert("RGBA")
    placed, info = renderer.place(
        raw,
        PlaceContext(
            level_id=job["level_id"],
            canvas_size=tuple(int(value) for value in job["canvas_size"]),
            frame=Frame.from_dict(job["frame"]),
            outside_color=config.outside_color,
            generation_mask=generation_mask,
            locked_mask=locked_mask,
            sent_input=load_image(job_dir / "input.png"),
            rescale_below_iou=config.execution.rescale_below_iou,
        ),
    )
    placed.paste(locked_pixels, (0, 0), locked_mask)
    return placed, info


def _generate(
    variant: dict[str, Any],
    job_dir: Path,
    job: dict[str, Any],
    base_generation: dict,
    output_path: Path,
) -> dict[str, Any]:
    client_config = dict(base_generation)
    client_config["quality"] = variant["quality"]
    width, height = job["input_size"]
    client_config["width"], client_config["height"] = int(width), int(height)
    # gpt-image-2 rejects input_fidelity outright -- "does not support the 'input_fidelity'
    # parameter", 400 before anything is generated -- and processes every input at high
    # fidelity anyway. Left here only for models that do accept it.
    if variant["input_fidelity"]:
        client_config["input_fidelity"] = variant["input_fidelity"]
    else:
        client_config.pop("input_fidelity", None)

    input_images = [
        job_dir / item["filename"]
        for item in job.get("context") or [{"filename": "input.png"}]
    ]
    missing = [str(path) for path in input_images if not path.is_file()]
    if missing:
        return {"error": f"missing context images: {', '.join(missing)}"}

    client = make_image_client(client_config)
    try:
        return client.generate(
            variant["prompt"],
            [str(path) for path in input_images],
            str(output_path),
            mask=None,
        )
    except (ImageClientError, OpenAIApiError) as exc:
        return {"error": str(exc)}


def run_bakeoff(
    root: Path,
    level_id: str,
    from_attempt: int,
    *,
    only: list[str] | None = None,
    open_images: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    config = load_config(root / "config.resolved.json")
    paths = level_paths(root, level_id.zfill(2))
    job_dir = paths["root"] / "jobs" / f"attempt_{from_attempt:03d}"
    job_path = job_dir / "job.json"
    if not job_path.is_file():
        raise FileNotFoundError(f"no job snapshot at {job_path}")
    job = read_json(job_path)
    current_prompt = (job_dir / "prompt.txt").read_text(encoding="utf-8")
    world_prompt = WORLD_PROMPT.read_text(encoding="utf-8")

    bakeoff = paths["root"] / "bakeoff" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bakeoff.mkdir(parents=True, exist_ok=True)
    (bakeoff / "world_prompt.txt").write_text(world_prompt, encoding="utf-8")
    (bakeoff / "current_prompt.txt").write_text(current_prompt, encoding="utf-8")
    shutil.copy2(job_dir / "input.png", bakeoff / "input.png")
    if (job_dir / "locked_overlap.png").is_file():
        shutil.copy2(job_dir / "locked_overlap.png", bakeoff / "locked_overlap.png")

    chosen = _variants(current_prompt, world_prompt)
    if only:
        unknown = [name for name in only if name not in {item["id"] for item in chosen}]
        if unknown:
            raise ValueError(f"unknown variants: {', '.join(unknown)}")
        by_id = {item["id"]: item for item in chosen}
        chosen = [by_id[name] for name in only]

    rows: list[dict[str, Any]] = []
    for variant in chosen:
        out_dir = bakeoff / variant["id"]
        out_dir.mkdir(parents=True)
        (out_dir / "prompt.txt").write_text(variant["prompt"], encoding="utf-8")
        generated_path = out_dir / "generated.png"
        print(f"\n=== {variant['id']}: {variant['label']} ===", flush=True)

        result = _generate(variant, job_dir, job, config.generation, generated_path)
        if result.get("error"):
            row = {
                "id": variant["id"],
                "label": variant["label"],
                "error": result["error"],
                "quality": variant["quality"],
                "input_fidelity": variant["input_fidelity"],
            }
            (out_dir / "generation_result.json").write_text(
                json.dumps(row, indent=2), encoding="utf-8"
            )
            print(f"  FAILED: {result['error'][:400]}", flush=True)
            rows.append(row)
            continue

        src = Path(result["output_path"])
        if src != generated_path and src.is_file():
            shutil.copy2(src, generated_path)
        result["output_path"] = str(generated_path)
        (out_dir / "generation_result.json").write_text(
            json.dumps(result, indent=2, default=str), encoding="utf-8"
        )

        try:
            normalized, info = _normalize(generated_path, job, job_dir, config)
        except Exception as exc:
            row = {
                "id": variant["id"],
                "label": variant["label"],
                "error": f"place/paste failed: {exc}",
                "quality": variant["quality"],
                "input_fidelity": variant["input_fidelity"],
                "generated": str(generated_path),
                "usage": result.get("usage") or {},
            }
            (out_dir / "place_info.json").write_text(
                json.dumps(row, indent=2, default=str), encoding="utf-8"
            )
            print(f"  FAILED after generate: {exc}", flush=True)
            rows.append(row)
            continue
        normalized_path = out_dir / "normalized.png"
        normalized.save(normalized_path)
        (out_dir / "place_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")

        usage = result.get("usage") or {}
        usd = _estimate_usd(usage)
        row = {
            "id": variant["id"],
            "label": variant["label"],
            "quality": variant["quality"],
            "input_fidelity": variant["input_fidelity"],
            "generated": str(generated_path),
            "normalized": str(normalized_path),
            "usage": usage,
            "usd_estimate": None if usd is None else round(usd, 4),
            "drift_px": info.get("drift_px"),
            "drift_applied": info.get("drift_applied"),
        }
        rows.append(row)
        usd_text = "n/a" if usd is None else f"${usd:.4f}"
        print(
            f"  tokens in={usage.get('input_tokens')} out={usage.get('output_tokens')} "
            f"est={usd_text}",
            flush=True,
        )
        print(f"  raw:         {generated_path}", flush=True)
        print(f"  after paste: {normalized_path}", flush=True)
        if open_images:
            _open_images(
                [
                    bakeoff / "input.png",
                    bakeoff / "locked_overlap.png",
                    generated_path,
                    normalized_path,
                ]
            )

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "level_id": level_id.zfill(2),
        "from_attempt": from_attempt,
        "source_job": str(job_path),
        "bakeoff": str(bakeoff),
        "rates_usd_per_million": USD_PER_MILLION,
        "variants": rows,
        "usd_estimate_total": round(
            sum(item["usd_estimate"] for item in rows if item.get("usd_estimate") is not None),
            4,
        ),
    }
    (bakeoff / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nsummary: {bakeoff / 'summary.json'}")
    print(f"estimated total: ${summary['usd_estimate_total']:.4f}")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("root", help="Prepared run root, e.g. generated/world_levels/sunspine_01")
    parser.add_argument("--level", default="02")
    parser.add_argument("--from-attempt", type=int, default=3, help="Job snapshot to reuse")
    parser.add_argument(
        "--only",
        help="Comma-separated variant ids: world_prompt,fidelity_high,world_prompt_fidelity_high,quality_high",
    )
    parser.add_argument("--no-open", action="store_true", help="Do not open images")
    args = parser.parse_args(argv)
    only = [part.strip() for part in args.only.split(",")] if args.only else None
    run_bakeoff(
        Path(args.root),
        args.level,
        args.from_attempt,
        only=only,
        open_images=not args.no_open,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
