"""Cheap-model bakeoff: one chunk, several models/sizes, cost + images in one folder.

Does not overwrite chunk heightmaps. Writes under
``levels/.../export/heightmap_cost/<variant>/``.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from ..collision.emit import chunk_entry, load_manifest
from ..image_client import ImageClientError, _resample_filter, make_image_client
from .align import QC_MAX_SHIFT_PX, QC_MIN_RESPONSE, align_generated
from .run_chunk import load_config, source_path_for_chunk

Image.MAX_IMAGE_PIXELS = None

# Enum-legal Leonardo sizes near source AR 1.466. Lite max is 1376×1376.
# gpt-image-2: edges ÷16, ≥655k px → 1024×704.
VARIANTS: list[dict[str, Any]] = [
    {
        "id": "leo_nb2_lite_1376x928",
        "need": "leonardo",
        "note": "Nano Banana 2 Lite, smallest near-AR size",
        "overrides": {
            "provider": "leonardo",
            "model": "nano-banana-2-lite",
            "width": 1376,
            "height": 928,
        },
    },
    {
        "id": "leo_flash_1536x1024",
        "need": "leonardo",
        "note": "Nano Banana 1 (gemini-2.5-flash-image)",
        "overrides": {
            "provider": "leonardo",
            "model": "gemini-2.5-flash-image",
            "width": 1536,
            "height": 1024,
        },
    },
    {
        "id": "leo_nb2_1696x1152",
        "need": "leonardo",
        "note": "Nano Banana 2, small",
        "overrides": {
            "provider": "leonardo",
            "model": "nano-banana-2",
            "width": 1696,
            "height": 1152,
        },
    },
    {
        "id": "gpt2_low_1024x704",
        "need": "openai",
        "note": "OpenAI gpt-image-2 quality=low, min-ish pixels",
        "overrides": {
            "provider": "openai",
            "model": "gpt-image-2",
            "quality": "low",
            "width": 1024,
            "height": 704,
            "timeout_seconds": 900,
        },
    },
    {
        "id": "gpt1_low_1024x1024",
        "need": "openai",
        "note": "OpenAI gpt-image-1 quality=low (square; cheaper if still listed)",
        "overrides": {
            "provider": "openai",
            "model": "gpt-image-1",
            "quality": "low",
            "width": 1024,
            "height": 1024,
            "timeout_seconds": 900,
        },
    },
    {
        "id": "leo_phoenix_1024x768",
        "need": "leonardo",
        "risky": True,
        "note": "First-party Phoenix; may reject image_reference",
        "overrides": {
            "provider": "leonardo",
            "model": "phoenix-v1.0",
            "width": 1024,
            "height": 768,
        },
    },
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _env_for(need: str) -> str:
    return "LEONARDO_API_KEY" if need == "leonardo" else "OPENAI_API_KEY"


def usd_from_api(api: dict[str, Any] | None) -> str:
    api = api or {}
    if api.get("cost_usd") is not None:
        try:
            return f"{float(api['cost_usd']):.4f}"
        except (TypeError, ValueError):
            pass
    usage = api.get("usage") or {}
    if usage.get("output_tokens") is not None:
        inp = float(usage.get("input_tokens") or 0)
        out = float(usage.get("output_tokens") or 0)
        return f"{inp / 1e6 * 10 + out / 1e6 * 40:.4f}"
    cost = ((api.get("create_response") or {}).get("generate") or {}).get("cost") or {}
    if str(cost.get("unit", "")).upper() == "DOLLARS" and cost.get("amount") is not None:
        try:
            return f"{float(cost['amount']):.4f}"
        except (TypeError, ValueError):
            return str(cost.get("amount"))
    return ""


def write_downscaled(source: Path, dest: Path, size: tuple[int, int]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as im:
        im.convert("RGBA").resize(size, _resample_filter()).save(dest)


def write_contact_sheet(out_root: Path, variant_ids: list[str]) -> Path | None:
    tiles: list[tuple[str, Image.Image]] = []
    for variant_id in variant_ids:
        preview = out_root / variant_id / "heightmap_preview.png"
        if not preview.is_file():
            continue
        with Image.open(preview) as im:
            rgb = im.convert("RGB")
            width = 640
            height = max(1, int(rgb.height * width / rgb.width))
            tiles.append((variant_id, rgb.resize((width, height), _resample_filter())))
    if not tiles:
        return None
    label_h = 28
    width = tiles[0][1].width
    height = sum(im.height + label_h for _, im in tiles)
    sheet = Image.new("RGB", (width, height), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for name, im in tiles:
        draw.rectangle((0, y, width, y + label_h), fill=(32, 32, 32))
        draw.text((8, y + 6), name, fill=(220, 220, 220))
        y += label_h
        sheet.paste(im, (0, y))
        y += im.height
    dest = out_root / "contact_sheet.png"
    sheet.save(dest)
    return dest


def run_variant(
    *,
    variant: dict[str, Any],
    base_config: dict[str, Any],
    source_path: Path,
    out_dir: Path,
    preserve: bool,
) -> dict[str, Any]:
    config = dict(base_config)
    config.update(variant["overrides"])
    config["preserve_existing"] = False
    config.pop("style_ids", None)

    paths = {
        "raw": out_dir / "heightmap_raw.png",
        "height": out_dir / "heightmap.png",
        "preview": out_dir / "heightmap_preview.png",
        "result": out_dir / "heightmap_result.json",
        "ref": out_dir / "reference.png",
    }
    if preserve and paths["height"].is_file() and paths["result"].is_file():
        prior = json.loads(paths["result"].read_text(encoding="utf-8"))
        prior["preserved"] = True
        return prior

    out_dir.mkdir(parents=True, exist_ok=True)
    gen_w = int(config["width"])
    gen_h = int(config["height"])
    ref = source_path
    if config.get("provider") == "openai":
        write_downscaled(source_path, paths["ref"], (gen_w, gen_h))
        ref = paths["ref"]

    t0 = time.monotonic()
    client = make_image_client(config)
    api = client.generate(str(config["prompt"]), [str(ref)], str(paths["raw"]))
    seconds = round(time.monotonic() - t0, 1)
    if not isinstance(api, dict):
        api = {"raw_api": api}
    qc = align_generated(
        paths["raw"],
        source_path,
        height_out=paths["height"],
        preview_out=paths["preview"],
        max_shift_px=int(config.get("qc_max_shift_px", QC_MAX_SHIFT_PX)),
        min_response=float(config.get("qc_min_response", QC_MIN_RESPONSE)),
    )
    result = {
        "id": variant["id"],
        "note": variant.get("note"),
        "provider": config.get("provider"),
        "model": config.get("model"),
        "quality": config.get("quality"),
        "width": gen_w,
        "height": gen_h,
        "seconds": seconds,
        "usd": usd_from_api(api),
        "qc": qc,
        "api": api,
        "output_path": str(paths["height"]),
        "status": "OK" if qc.get("ok") else "QC_FAIL",
    }
    paths["result"].write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def write_log(out_root: Path, rows: list[dict[str, Any]]) -> Path:
    log = out_root / "cost.tsv"
    fields = [
        "when",
        "status",
        "id",
        "provider",
        "model",
        "quality",
        "size",
        "seconds",
        "usd",
        "dx",
        "dy",
        "response",
        "qc_ok",
        "note",
        "error",
    ]
    with log.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for row in rows:
            qc = row.get("qc") or {}
            writer.writerow(
                {
                    "when": row.get("when", ""),
                    "status": row.get("status", ""),
                    "id": row.get("id", ""),
                    "provider": row.get("provider", ""),
                    "model": row.get("model", ""),
                    "quality": row.get("quality") or "",
                    "size": f"{row.get('width', '')}x{row.get('height', '')}",
                    "seconds": row.get("seconds", ""),
                    "usd": row.get("usd", ""),
                    "dx": qc.get("dx", ""),
                    "dy": qc.get("dy", ""),
                    "response": qc.get("response", ""),
                    "qc_ok": qc.get("ok", ""),
                    "note": row.get("note", ""),
                    "error": row.get("error", ""),
                }
            )
    return log


def selected_variants(*, only: str | None, include_risky: bool) -> list[dict[str, Any]]:
    wanted = {item.strip() for item in only.split(",")} if only else None
    out: list[dict[str, Any]] = []
    for variant in VARIANTS:
        if wanted is not None and variant["id"] not in wanted:
            continue
        if variant.get("risky") and not include_risky and wanted is None:
            continue
        out.append(variant)
    if wanted is not None:
        missing = wanted - {v["id"] for v in out}
        if missing:
            raise ValueError(f"unknown variant id(s): {', '.join(sorted(missing))}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cheap heightmap bakeoff: models/sizes, cost.tsv + images."
    )
    parser.add_argument("--chunk", default="chunk_00_02")
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/sunspine_7x6_play/export/sam3_chunks/insert_manifest.json",
    )
    parser.add_argument(
        "--config",
        default="tools/painted_map_pipeline/heightmap.sunspine.json",
    )
    parser.add_argument(
        "--out",
        default="levels/Frostreach/sunspine_7x6_play/export/heightmap_cost",
    )
    parser.add_argument("--only", help="Comma-separated variant ids")
    parser.add_argument(
        "--include-risky",
        action="store_true",
        help="Also run first-party models that may reject image_reference",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run even if the variant folder already has heightmap.png",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the variant list and skip API calls",
    )
    args = parser.parse_args(argv)

    repo = _repo_root()
    variants = selected_variants(only=args.only, include_risky=args.include_risky)
    if args.dry_run:
        for variant in variants:
            env = _env_for(variant["need"])
            have = "key set" if os.environ.get(env) else f"{env} unset"
            print(f"{variant['id']}\t{variant['need']}\t{have}\t{variant.get('note', '')}")
        return 0

    base = load_config((repo / args.config).resolve())
    manifest = load_manifest((repo / args.manifest).resolve())
    chunk = chunk_entry(manifest, args.chunk)
    source_path = source_path_for_chunk(chunk, repo)
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing source for {args.chunk}: {source_path}")
    out_root = Path(args.out)
    if not out_root.is_absolute():
        out_root = (repo / out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")

    for variant in variants:
        env = _env_for(variant["need"])
        row: dict[str, Any] = {
            "when": now,
            "id": variant["id"],
            "note": variant.get("note"),
            "provider": variant["overrides"].get("provider"),
            "model": variant["overrides"].get("model"),
            "quality": variant["overrides"].get("quality"),
            "width": variant["overrides"].get("width"),
            "height": variant["overrides"].get("height"),
        }
        if not os.environ.get(env):
            row["status"] = "SKIP"
            row["error"] = f"{env} unset"
            print(f"SKIP {variant['id']}: {env} unset")
            rows.append(row)
            continue
        print(f"RUN  {variant['id']} ...", flush=True)
        try:
            result = run_variant(
                variant=variant,
                base_config=base,
                source_path=source_path,
                out_dir=out_root / variant["id"],
                preserve=not args.force,
            )
            result["when"] = now
            if result.get("preserved") and result.get("status") != "QC_FAIL":
                result["status"] = "KEEP"
            print(
                f"{result.get('status')} {variant['id']} {result.get('seconds')}s "
                f"usd={result.get('usd')} qc={result.get('qc', {}).get('ok')}"
            )
            rows.append(result)
        except (ImageClientError, OSError, ValueError) as exc:
            row["status"] = "FAIL"
            row["error"] = str(exc)[:200]
            print(f"FAIL {variant['id']}: {exc}")
            rows.append(row)

    log = write_log(out_root, rows)
    try:
        write_contact_sheet(out_root, [variant["id"] for variant in variants])
    except OSError:
        pass
    print(f"\nWrote {log}")
    if all(r.get("status") == "SKIP" for r in rows):
        print("No keys set. export LEONARDO_API_KEY and/or OPENAI_API_KEY, then re-run.")
        return 0
    return 0 if any(r.get("status") in {"OK", "KEEP", "QC_FAIL"} for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
