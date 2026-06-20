from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from .insert_chunks import insert_painted_chunks
from .pipeline import _resolve_paths


def _resample_filter():
    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS", Image.BICUBIC)


def _load_config(config_path: Path):
    raw_config = json.loads(config_path.read_text(encoding="utf-8"))
    return _resolve_paths(raw_config, config_path.parent)


def _load_manifest(output_dir: Path):
    manifest_path = output_dir / "chunks" / "chunks_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Chunk manifest not found: {manifest_path}. Run the pipeline prep first."
        )
    return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8"))


def _find_chunk(manifest: dict, chunk_id: str):
    for chunk in manifest.get("chunks", []):
        if chunk.get("chunk_id") == chunk_id:
            return chunk
    available = ", ".join(chunk.get("chunk_id", "<unknown>") for chunk in manifest.get("chunks", []))
    raise ValueError(f"Chunk {chunk_id!r} not found. Available chunks: {available}")


def _source_image_for_size(chunk: dict):
    painted_path = Path(chunk["painted_image"])
    context_source = painted_path.parent / "context" / "source.png"
    if context_source.exists():
        return context_source
    source_path = Path(chunk["source_image"])
    if source_path.exists():
        return source_path
    raise FileNotFoundError(f"No source image found for chunk {chunk.get('chunk_id')!r}")


def apply_painted_chunk(config_path, chunk_id, generated_image, insert=False):
    config_path = Path(config_path).resolve()
    generated_image = Path(generated_image).resolve()
    if not generated_image.exists():
        raise FileNotFoundError(f"Generated image not found: {generated_image}")

    config = _load_config(config_path)
    output_dir = Path(config["output_dir"])
    manifest_path, manifest = _load_manifest(output_dir)
    chunk = _find_chunk(manifest, chunk_id)

    source_image = _source_image_for_size(chunk)
    output_path = Path(chunk["painted_image"])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source_image) as source:
        working_size = source.size
    with Image.open(generated_image) as generated:
        original_size = generated.size
        painted = generated.convert("RGBA").resize(working_size, _resample_filter())
        painted.save(output_path)

    context_dir = output_path.parent / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "provider": "external_agent_image",
        "chunk_id": chunk_id,
        "generated_image": str(generated_image),
        "source_image_for_size": str(source_image),
        "output_path": str(output_path.resolve()),
        "original_size": list(original_size),
        "resized_to": list(working_size),
        "world_rect": chunk.get("world_rect"),
        "source_rect_with_overlap": chunk.get("source_rect_with_overlap"),
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "preserved_for_reruns": True,
    }

    if insert:
        painted_tmx_path = Path(
            config.get("painted_tmx_path")
            or (Path(config["tmx_path"]).parent / "map_painted.tmx")
        )
        result["insert"] = insert_painted_chunks(
            config["tmx_path"],
            manifest_path,
            painted_tmx_path,
        )

    (context_dir / "image_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Apply an externally generated painted image to one TMX chunk."
    )
    parser.add_argument("--config", required=True, help="Path to painted-map pipeline config JSON.")
    parser.add_argument("--chunk-id", required=True, help="Chunk id to update, e.g. chunk_01_00.")
    parser.add_argument(
        "--generated-image",
        required=True,
        help="Path to the externally generated painted chunk image.",
    )
    parser.add_argument(
        "--insert",
        action="store_true",
        help="Rebuild the configured map_painted.tmx after applying the chunk.",
    )
    args = parser.parse_args(argv)

    result = apply_painted_chunk(
        args.config,
        args.chunk_id,
        args.generated_image,
        insert=args.insert,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
