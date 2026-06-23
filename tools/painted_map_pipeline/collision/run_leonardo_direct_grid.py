"""Batch Leonardo direct collision for every chunk in insert_manifest.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from .emit import load_manifest, tmx_placement_for_chunk
from .leonardo_collision import finish_from_raw, run_leonardo_collision


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _chunk_has_valid_output(output_dir: Path, expected_size: tuple[int, int]) -> bool:
    raw = output_dir / "segmentation_raw.png"
    sprite = output_dir / "collision_sprite.png"
    preview = output_dir / "walkable_preview.png"
    if not (raw.exists() and sprite.exists() and preview.exists()):
        return False
    try:
        with Image.open(raw) as im:
            return im.size == expected_size
    except OSError:
        return False


def run_grid(args: argparse.Namespace) -> Path:
    repo = _repo_root()
    manifest_path = (repo / args.manifest).resolve()
    manifest = load_manifest(manifest_path)
    reference_tmx = (repo / args.reference_tmx).resolve()
    output_root = (repo / args.output_dir).resolve()
    leonardo_config = json.loads((repo / args.leonardo_config).resolve().read_text(encoding="utf-8"))
    if args.preserve_existing:
        leonardo_config["preserve_existing"] = True

    prompt_path = Path(args.direct_prompt).resolve() if args.direct_prompt else None
    chunk_filter = set(args.chunks.split(",")) if args.chunks else None

    results = []
    chunks = manifest.get("chunks", [])
    total = len(chunks)

    for index, chunk in enumerate(chunks, start=1):
        chunk_id = chunk.get("chunk_id") or Path(chunk["painted_image"]).stem
        if chunk_filter and chunk_id not in chunk_filter:
            continue

        painted_path = Path(chunk["painted_image"])
        if not painted_path.is_absolute():
            painted_path = (repo / painted_path).resolve()
        if not painted_path.exists():
            results.append({"chunk_id": chunk_id, "error": f"missing painted image: {painted_path}"})
            print(f"[{index}/{total}] SKIP {chunk_id}: missing source", flush=True)
            continue

        output_dir = output_root / chunk_id / "leonardo_direct"
        placement = tmx_placement_for_chunk(chunk, manifest, reference_tmx=reference_tmx)

        with Image.open(painted_path) as painted:
            expected_size = painted.size

        if leonardo_config.get("preserve_existing") and _chunk_has_valid_output(output_dir, expected_size):
            print(f"[{index}/{total}] KEEP {chunk_id} (existing output)", flush=True)
            results.append({"chunk_id": chunk_id, "status": "preserved", "output_dir": str(output_dir)})
            continue

        print(f"[{index}/{total}] RUN  {chunk_id} ...", flush=True)
        try:
            if args.from_raw and (output_dir / "segmentation_raw.png").exists():
                finish_from_raw(
                    chunk_id=chunk_id,
                    painted_path=painted_path,
                    output_dir=output_dir,
                    placement=placement,
                    leonardo_config=leonardo_config,
                    preview_map=args.preview_map,
                )
                status = "reparsed"
            else:
                run_leonardo_collision(
                    chunk_id=chunk_id,
                    painted_path=painted_path,
                    output_dir=output_dir,
                    placement=placement,
                    leonardo_config=leonardo_config,
                    mode="direct",
                    preview_map=args.preview_map,
                    prompt_path=prompt_path,
                )
                status = "ok"
            results.append({"chunk_id": chunk_id, "status": status, "output_dir": str(output_dir)})
            print(f"[{index}/{total}] DONE {chunk_id}", flush=True)
        except Exception as exc:
            results.append({"chunk_id": chunk_id, "status": "error", "error": str(exc)})
            print(f"[{index}/{total}] FAIL {chunk_id}: {exc}", flush=True)

    summary = {
        "manifest": str(manifest_path),
        "output_root": str(output_root),
        "total_chunks": total,
        "results": results,
        "ok": sum(1 for r in results if r.get("status") in {"ok", "preserved", "reparsed"}),
        "failed": sum(1 for r in results if r.get("status") == "error"),
    }
    summary_path = output_root / "leonardo_direct_batch_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nBatch complete: {summary['ok']} ok, {summary['failed']} failed -> {summary_path}", flush=True)
    return summary_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Leonardo direct collision for all manifest chunks.")
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
    )
    parser.add_argument("--reference-tmx", default="levels/Frostreach/expanse/map.tmx")
    parser.add_argument("--output-dir", default="levels/Frostreach/expanse/export/collision_trial")
    parser.add_argument(
        "--leonardo-config",
        default="tools/painted_map_pipeline/collision/leonardo_collision.config.example.json",
    )
    parser.add_argument("--direct-prompt", help="Override collision_direct_prompt.txt")
    parser.add_argument("--preview-map", action="store_true")
    parser.add_argument("--preserve-existing", action="store_true", default=True)
    parser.add_argument("--no-preserve-existing", action="store_false", dest="preserve_existing")
    parser.add_argument("--from-raw", action="store_true", help="Re-parse existing raw PNGs only")
    parser.add_argument("--chunks", help="Comma-separated chunk ids to run (default: all)")
    args = parser.parse_args(argv)
    run_grid(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
