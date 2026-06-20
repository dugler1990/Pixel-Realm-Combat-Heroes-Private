from __future__ import annotations

import argparse
import json
from pathlib import Path

from .prompt_builder import build_context_packs
from .pipeline import _resolve_paths


def refresh_context(config_path, chunk_ids=None):
    config_path = Path(config_path)
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    config = _resolve_paths(raw_config, config_path.parent)

    output_dir = Path(config["output_dir"])
    chunks_manifest_path = output_dir / "chunks" / "chunks_manifest.json"
    if not chunks_manifest_path.exists():
        raise FileNotFoundError(
            f"Chunk manifest not found: {chunks_manifest_path}. Run the full pipeline once first."
        )

    contact_sheet = output_dir / "asset_contact_sheet.png"
    chunks_manifest = json.loads(chunks_manifest_path.read_text(encoding="utf-8"))
    context_manifest = build_context_packs(
        chunks_manifest,
        output_dir,
        config,
        asset_contact_sheet=str(contact_sheet) if contact_sheet.exists() else None,
        chunk_ids=chunk_ids,
    )

    return {
        "config_path": str(config_path),
        "chunks_manifest": str(chunks_manifest_path),
        "context_manifest": str(output_dir / "context_manifest.json"),
        "updated_packs": len(context_manifest.get("packs", [])),
        "chunk_ids": chunk_ids or "all",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Refresh painted-map chunk prompts and context images without rerendering."
    )
    parser.add_argument("config", help="Path to painted-map pipeline config JSON.")
    parser.add_argument(
        "--chunk-id",
        action="append",
        dest="chunk_ids",
        help="Only refresh one chunk id. Repeat for multiple chunks.",
    )
    args = parser.parse_args(argv)

    result = refresh_context(args.config, chunk_ids=args.chunk_ids)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
