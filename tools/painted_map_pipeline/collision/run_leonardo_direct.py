"""Leonardo-only collision pass: painted chunk in, walkable segmentation out. No mechanical hint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .emit import chunk_entry, load_manifest, tmx_placement_for_chunk
from .leonardo_collision import finish_from_raw, run_leonardo_collision
from .variant_paths import DEFAULT_LEONARDO_VARIANT, chunk_variant_dir


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run Leonardo direct collision segmentation (no mechanical preprocessing)."
    )
    parser.add_argument("--chunk", default="chunk_06_06")
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
    )
    parser.add_argument("--reference-tmx", default="levels/Frostreach/expanse/map.tmx")
    parser.add_argument(
        "--output-dir",
        default="levels/Frostreach/expanse/export/collision_trial",
        help="Root trial dir; writes {output-dir}/{chunk}/{variant}/",
    )
    parser.add_argument(
        "--variant",
        default=DEFAULT_LEONARDO_VARIANT,
        help=f"Subfolder under each chunk (default: {DEFAULT_LEONARDO_VARIANT})",
    )
    parser.add_argument(
        "--leonardo-config",
        default="tools/painted_map_pipeline/collision/leonardo_collision.config.example.json",
    )
    parser.add_argument("--direct-prompt", help="Override collision_direct_prompt.txt")
    parser.add_argument("--preview-map", action="store_true")
    parser.add_argument(
        "--from-raw",
        action="store_true",
        help="Re-parse existing segmentation_raw.png (no API call)",
    )
    args = parser.parse_args(argv)

    repo = _repo_root()
    manifest = load_manifest((repo / args.manifest).resolve())
    chunk = chunk_entry(manifest, args.chunk)
    painted_path = Path(chunk["painted_image"])
    if not painted_path.is_absolute():
        painted_path = (repo / painted_path).resolve()

    reference_tmx = (repo / args.reference_tmx).resolve()
    output_dir = chunk_variant_dir((repo / args.output_dir).resolve(), args.chunk, args.variant)
    leonardo_config = json.loads((repo / args.leonardo_config).resolve().read_text(encoding="utf-8"))
    placement = tmx_placement_for_chunk(chunk, manifest, reference_tmx=reference_tmx)

    prompt_path = Path(args.direct_prompt).resolve() if args.direct_prompt else None

    if args.from_raw:
        finish_from_raw(
            chunk_id=args.chunk,
            painted_path=painted_path,
            output_dir=output_dir,
            placement=placement,
            leonardo_config=leonardo_config,
            preview_map=args.preview_map,
            variant=args.variant,
        )
    else:
        run_leonardo_collision(
            chunk_id=args.chunk,
            painted_path=painted_path,
            output_dir=output_dir,
            placement=placement,
            leonardo_config=leonardo_config,
            mode="direct",
            preview_map=args.preview_map,
            prompt_path=prompt_path,
            variant=args.variant,
        )
    print(f"Leonardo direct collision -> {output_dir}")
    print(f"  raw:     {output_dir / 'segmentation_raw.png'}")
    print(f"  preview: {output_dir / 'walkable_preview.png'}")
    print(f"  sprite:  {output_dir / 'collision_sprite.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
