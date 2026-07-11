"""Run Roboflow Custom Workflow on all manifest chunks sequentially."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..emit import load_manifest
from .roboflow_workflow import WorkflowError, chunk_output_dir, load_config
from .run_workflow_chunk import run_workflow_chunk


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Roboflow workflow obstacle polygons for all painted chunks (sequential)."
    )
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
    )
    parser.add_argument(
        "--config",
        default="tools/painted_map_pipeline/collision/sam3/sam3.config.example.json",
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

        out_dir = chunk_output_dir(config, repo, chunk_id)
        if args.preserve_existing and (out_dir / "polygons.json").exists():
            print(f"[{index}/{total}] KEEP {chunk_id}")
            ok += 1
            continue

        print(f"[{index}/{total}] RUN  {chunk_id} ...", flush=True)
        try:
            run_workflow_chunk(
                chunk_id=chunk_id,
                manifest_path=manifest_path,
                config=config,
                repo=repo,
            )
            print(f"[{index}/{total}] DONE {chunk_id}")
            ok += 1
        except (WorkflowError, OSError, FileNotFoundError) as exc:
            print(f"[{index}/{total}] FAIL {chunk_id}: {exc}")
            failed += 1

    print(f"\nBatch complete: {ok} ok, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
