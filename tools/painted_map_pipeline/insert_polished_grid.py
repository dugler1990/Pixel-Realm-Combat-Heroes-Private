"""Build an insert manifest from grid export + polished PNGs, then update map.tmx."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from .insert_chunks import insert_painted_chunks


def build_insert_manifest(
    grid_manifest_path: Path,
    polished_dir: Path,
    *,
    output_path: Path | None = None,
) -> dict:
    grid_manifest_path = Path(grid_manifest_path).resolve()
    polished_dir = Path(polished_dir).resolve()
    manifest = json.loads(grid_manifest_path.read_text(encoding="utf-8"))

    chunks = []
    for chunk in manifest.get("chunks", []):
        chunk_id = chunk["chunk_id"]
        polished_path = polished_dir / f"{chunk_id}.png"
        if not polished_path.exists():
            raise FileNotFoundError(f"Missing polished chunk: {polished_path}")
        with Image.open(polished_path) as image:
            image_size = list(image.size)
        chunks.append(
            {
                "chunk_id": chunk_id,
                "grid": chunk.get("grid"),
                "painted_image": str(polished_path),
                "world_rect": [int(v) for v in chunk["world_rect"]],
                "image_size": image_size,
                "padded": chunk.get("padded", False),
            }
        )

    insert_manifest = {
        "source_grid_manifest": str(grid_manifest_path),
        "polished_dir": str(polished_dir),
        "grid_size": manifest.get("grid_size"),
        "chunk_size_px": manifest.get("chunk_size_px"),
        "grid_world_size": manifest.get("grid_world_size"),
        "chunks": chunks,
    }
    if output_path:
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(insert_manifest, indent=2), encoding="utf-8")
    return insert_manifest


def insert_polished_grid(
    *,
    grid_manifest_path: Path,
    polished_dir: Path,
    tmx_path: Path,
    output_tmx_path: Path | None = None,
    insert_manifest_path: Path | None = None,
) -> dict:
    tmx_path = Path(tmx_path).resolve()
    output_tmx_path = Path(output_tmx_path or tmx_path).resolve()
    manifest_path = insert_manifest_path or (polished_dir / "insert_manifest.json")
    build_insert_manifest(grid_manifest_path, polished_dir, output_path=manifest_path)
    insert_result = insert_painted_chunks(tmx_path, manifest_path, output_tmx_path)
    return {
        "insert_manifest": str(manifest_path),
        "insert": insert_result,
    }


def _resolve_path(raw: str, *, must_exist: bool = False) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    repo_root = Path(__file__).resolve().parents[2]
    if must_exist:
        for root in (Path.cwd(), repo_root):
            candidate = (root / path).resolve()
            if candidate.exists():
                return candidate
    return (repo_root / path).resolve()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Insert polished PaintedGround grid into map.tmx.")
    parser.add_argument(
        "--grid-manifest",
        default="levels/Frostreach/expanse/export/painted_4k/grid_manifest.json",
    )
    parser.add_argument(
        "--polished-dir",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo",
    )
    parser.add_argument(
        "--tmx",
        default="levels/Frostreach/expanse/map.tmx",
    )
    parser.add_argument(
        "--output-tmx",
        default=None,
        help="Defaults to --tmx (in-place update).",
    )
    parser.add_argument(
        "--insert-manifest",
        default=None,
        help="Optional path to write insert_manifest.json",
    )
    args = parser.parse_args(argv)

    result = insert_polished_grid(
        grid_manifest_path=_resolve_path(args.grid_manifest, must_exist=True),
        polished_dir=_resolve_path(args.polished_dir, must_exist=True),
        tmx_path=_resolve_path(args.tmx, must_exist=True),
        output_tmx_path=_resolve_path(args.output_tmx) if args.output_tmx else None,
        insert_manifest_path=_resolve_path(args.insert_manifest) if args.insert_manifest else None,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
