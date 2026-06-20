from __future__ import annotations

import argparse
import json
from pathlib import Path

from .asset_contact_sheet import build_asset_contact_sheet
from .image_client import generate_painted_chunks
from .insert_chunks import insert_painted_chunks
from .prompt_builder import build_context_packs
from .render_tmx import render_tmx
from .slice_chunks import slice_chunks


def _resolve_paths(config: dict, base_dir: Path):
    resolved = dict(config)
    for key in ("tmx_path", "output_dir", "painted_tmx_path", "world_reference", "region_reference"):
        value = resolved.get(key)
        if value:
            resolved[key] = str((base_dir / value).resolve() if not Path(value).is_absolute() else Path(value))
    resolved["asset_reference_paths"] = [
        str((base_dir / p).resolve() if not Path(p).is_absolute() else Path(p))
        for p in resolved.get("asset_reference_paths", [])
    ]
    return resolved


def run_pipeline(config_path):
    config_path = Path(config_path)
    base_dir = config_path.parent
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    config = _resolve_paths(raw_config, base_dir)

    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    rough_full = output_dir / "rough_full.png"
    render_result = render_tmx(
        config["tmx_path"],
        rough_full,
        include_layers=config.get("layers_to_render"),
        exclude_layers=config.get("layers_to_exclude"),
    )

    chunks_dir = output_dir / "chunks"
    chunks_manifest = slice_chunks(
        rough_full,
        chunks_dir,
        chunk_size=config.get("world_chunk_size", config.get("chunk_size", [3000, 2000])),
        overlap=config.get("overlap", 192),
        generation_max_size=config.get("generation_max_size"),
    )

    contact_sheet_path = output_dir / "asset_contact_sheet.png"
    contact_result = build_asset_contact_sheet(
        config.get("asset_reference_paths", []),
        contact_sheet_path,
        max_images=int(config.get("asset_contact_sheet_max_images", 48)),
    )

    context_manifest = build_context_packs(
        chunks_manifest,
        output_dir,
        config,
        asset_contact_sheet=contact_result["output_path"],
    )

    image_result = generate_painted_chunks(context_manifest, config.get("image_generation", {}))

    painted_tmx_path = Path(config.get("painted_tmx_path") or (Path(config["tmx_path"]).parent / "map_painted.tmx"))
    insert_result = insert_painted_chunks(
        config["tmx_path"],
        chunks_dir / "chunks_manifest.json",
        painted_tmx_path,
    )

    summary = {
        "config_path": str(config_path),
        "render": render_result,
        "chunks_manifest": str(chunks_dir / "chunks_manifest.json"),
        "context_manifest": str(output_dir / "context_manifest.json"),
        "contact_sheet": contact_result,
        "image_generation": image_result,
        "insert": insert_result,
    }
    (output_dir / "pipeline_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate AI-painted TMX background chunks.")
    parser.add_argument("config", help="Path to pipeline config JSON.")
    args = parser.parse_args(argv)
    summary = run_pipeline(args.config)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

