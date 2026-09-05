"""Generate heightmaps for all (or listed) manifest chunks."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..collision.emit import load_manifest
from ..image_client import ImageClientError
from .align import HeightmapQCError
from .run_chunk import load_config, run_heightmap_chunk


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ImageClient heightmaps for painted chunks (sequential)."
    )
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/sunspine_7x6_play/export/sam3_chunks/insert_manifest.json",
    )
    parser.add_argument(
        "--config",
        default="tools/painted_map_pipeline/heightmap.sunspine.json",
    )
    parser.add_argument("--preserve-existing", action="store_true", default=True)
    parser.add_argument("--no-preserve-existing", action="store_false", dest="preserve_existing")
    parser.add_argument("--chunks", help="Comma-separated chunk ids (default: all)")
    args = parser.parse_args(argv)

    repo = _repo_root()
    config = load_config((repo / args.config).resolve())
    manifest_path = (repo / args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    chunk_filter = set(args.chunks.split(",")) if args.chunks else None

    chunks = manifest.get("chunks", [])
    total = len(chunks)
    ok = 0
    failed = 0

    for index, chunk in enumerate(chunks, start=1):
        chunk_id = chunk.get("chunk_id") or Path(chunk["painted_image"]).stem
        if chunk_filter and chunk_id not in chunk_filter:
            continue
        print(f"[{index}/{total}] RUN  {chunk_id} ...", flush=True)
        try:
            result = run_heightmap_chunk(
                chunk_id=chunk_id,
                manifest_path=manifest_path,
                config=config,
                repo=repo,
                preserve_existing=args.preserve_existing,
            )
            if result.get("preserved"):
                print(f"[{index}/{total}] KEEP {chunk_id}")
            else:
                qc = result.get("qc") or {}
                print(
                    f"[{index}/{total}] DONE {chunk_id} "
                    f"dx={qc.get('dx')} dy={qc.get('dy')} response={qc.get('response')}"
                )
            ok += 1
        except (HeightmapQCError, ImageClientError, OSError, FileNotFoundError, KeyError) as exc:
            print(f"[{index}/{total}] FAIL {chunk_id}: {exc}")
            failed += 1

    print(f"\nBatch complete: {ok} ok, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
