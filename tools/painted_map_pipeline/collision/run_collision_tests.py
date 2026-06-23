"""Run all collision test variants for one chunk (mechanical + Leonardo direct + Leonardo hint)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from PIL import Image

from .derive import DeriveConfig, derive_collision_masks
from .emit import chunk_entry, load_manifest, tmx_placement_for_chunk
from .leonardo_collision import run_leonardo_collision
from .package import build_compare_sheet, masks_from_derive_result, write_collision_package


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_derive_config(path: Path | None) -> DeriveConfig:
    if path is None or not path.exists():
        return DeriveConfig()
    data = _load_json(path)
    return DeriveConfig.from_mapping(data.get("derive", data))


from .hint_image import mechanical_flat_map, painted_with_mechanical_overlay, side_by_side_hint


def _prepare_leonardo_inputs(
    *,
    chunk_id: str,
    painted_path: Path,
    chunk_root: Path,
    derive_config: DeriveConfig,
    summary: dict,
) -> None:
    prep_dir = chunk_root / "leonardo_inputs"
    prep_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(painted_path) as painted:
        painted.convert("RGB").save(prep_dir / "direct_input.png")
        result = derive_collision_masks(painted, derive_config)
        mechanical_flat_map(result).save(prep_dir / "mechanical_flat.png")
        painted_with_mechanical_overlay(painted, result, alpha=0.55).save(prep_dir / "hint_overlay_input.png")
        side_by_side_hint(painted, result).save(prep_dir / "hint_side_by_side_input.png")
    summary["leonardo_inputs"] = str(prep_dir)
    print(f"Prepared Leonardo inputs at {prep_dir}")


def run(args: argparse.Namespace) -> Path:
    repo = _repo_root()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = (repo / manifest_path).resolve()

    manifest = load_manifest(manifest_path)
    chunk = chunk_entry(manifest, args.chunk)
    painted_path = Path(chunk["painted_image"])
    if not painted_path.is_absolute():
        painted_path = (repo / painted_path).resolve()

    reference_tmx = Path(args.reference_tmx)
    if not reference_tmx.is_absolute():
        reference_tmx = (repo / reference_tmx).resolve()

    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = (repo / output_root).resolve()
    chunk_root = output_root / args.chunk
    chunk_root.mkdir(parents=True, exist_ok=True)

    placement = tmx_placement_for_chunk(chunk, manifest, reference_tmx=reference_tmx)
    derive_config = _load_derive_config(Path(args.derive_config) if args.derive_config else None)

    variants_run: list[tuple[str, Path]] = []
    summary: dict = {"chunk_id": args.chunk, "variants": {}}

    if not args.skip_mechanical:
        mech_dir = chunk_root / "mechanical_v2"
        with Image.open(painted_path) as painted:
            result = derive_collision_masks(painted, derive_config)
            write_collision_package(
                chunk_dir=mech_dir,
                chunk_id=args.chunk,
                painted_path=painted_path,
                painted_image=painted,
                masks=masks_from_derive_result(result),
                placement=placement,
                layer_name=args.layer_name,
                variant="mechanical_v2",
                extra_meta={"derive_config": derive_config.__dict__},
                preview_map=args.preview_map,
            )
        variants_run.append(("mechanical_v2", mech_dir))
        summary["variants"]["mechanical_v2"] = str(mech_dir)

    if args.prepare_leonardo_inputs:
        _prepare_leonardo_inputs(
            chunk_id=args.chunk,
            painted_path=painted_path,
            chunk_root=chunk_root,
            derive_config=derive_config,
            summary=summary,
        )

    leonardo_config = None
    if not args.mechanical_only and (args.leonardo_direct or args.leonardo_hint):
        if args.leonardo_config:
            leonardo_config = _load_json(Path(args.leonardo_config))
        elif (Path(__file__).parent / "leonardo_collision.config.example.json").exists():
            leonardo_config = _load_json(Path(__file__).parent / "leonardo_collision.config.example.json")

        has_api_key = bool(
            os.environ.get((leonardo_config or {}).get("api_key_env", "LEONARDO_API_KEY"), "").strip()
        )

        if not has_api_key:
            print("WARNING: LEONARDO_API_KEY not set; skipping Leonardo variants.")
        elif leonardo_config is None:
            print("WARNING: No leonardo config; skipping Leonardo variants.")
        else:
            if args.leonardo_direct:
                direct_dir = chunk_root / "leonardo_direct"
                try:
                    run_leonardo_collision(
                        chunk_id=args.chunk,
                        painted_path=painted_path,
                        output_dir=direct_dir,
                        placement=placement,
                        leonardo_config=leonardo_config,
                        mode="direct",
                        layer_name=args.layer_name,
                        preview_map=args.preview_map,
                        prompt_path=Path(args.direct_prompt) if args.direct_prompt else None,
                    )
                    variants_run.append(("leonardo_direct", direct_dir))
                    summary["variants"]["leonardo_direct"] = str(direct_dir)
                except Exception as exc:
                    summary["variants"]["leonardo_direct"] = {"error": str(exc)}
                    print(f"leonardo_direct failed: {exc}")

            if args.leonardo_hint:
                hint_dir = chunk_root / "leonardo_hint"
                try:
                    run_leonardo_collision(
                        chunk_id=args.chunk,
                        painted_path=painted_path,
                        output_dir=hint_dir,
                        placement=placement,
                        leonardo_config=leonardo_config,
                        mode="hint",
                        mechanical_config=derive_config,
                        layer_name=args.layer_name,
                        preview_map=args.preview_map,
                        prompt_path=Path(args.hint_prompt) if args.hint_prompt else None,
                    )
                    variants_run.append(("leonardo_hint", hint_dir))
                    summary["variants"]["leonardo_hint"] = str(hint_dir)
                except Exception as exc:
                    summary["variants"]["leonardo_hint"] = {"error": str(exc)}
                    print(f"leonardo_hint failed: {exc}")

    compare_path = chunk_root / "compare_variants.png"
    build_compare_sheet(variants_run, compare_path)
    summary["compare_sheet"] = str(compare_path)
    (chunk_root / "test_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Collision tests for {args.chunk} -> {chunk_root}")
    for label, path in variants_run:
        print(f"  {label}: {path / 'walkable_preview.png'}")
    if compare_path.exists():
        print(f"  compare: {compare_path}")
    return chunk_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run collision test variants for one painted chunk.")
    parser.add_argument("--chunk", default="chunk_06_06")
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
    )
    parser.add_argument("--reference-tmx", default="levels/Frostreach/expanse/map.tmx")
    parser.add_argument("--output-dir", default="levels/Frostreach/expanse/export/collision_trial")
    parser.add_argument(
        "--derive-config",
        default="tools/painted_map_pipeline/collision/chunk_06_06.config.json",
    )
    parser.add_argument(
        "--leonardo-config",
        default="tools/painted_map_pipeline/collision/leonardo_collision.config.example.json",
    )
    parser.add_argument("--direct-prompt", help="Override collision_direct_prompt.txt")
    parser.add_argument("--hint-prompt", help="Override collision_hint_prompt.txt")
    parser.add_argument("--layer-name", default="PaintedCollision")
    parser.add_argument("--preview-map", action="store_true")
    parser.add_argument("--skip-mechanical", action="store_true")
    parser.add_argument("--leonardo-direct", action="store_true", help="Run Leonardo direct segmentation")
    parser.add_argument("--leonardo-hint", action="store_true", help="Run Leonardo with mechanical overlay hint")
    parser.add_argument(
        "--leo-only",
        action="store_true",
        help="Leonardo direct only — no mechanical, no hint (recommended)",
    )
    parser.add_argument("--all", action="store_true", help="Run mechanical + both Leonardo modes")
    parser.add_argument("--mechanical-only", action="store_true", help="Skip Leonardo variants")
    parser.add_argument(
        "--prepare-leonardo-inputs",
        action="store_true",
        help="Write Leonardo input PNGs (direct + hint) without calling the API",
    )
    args = parser.parse_args(argv)

    if args.leo_only:
        args.skip_mechanical = True
        args.leonardo_direct = True
        args.leonardo_hint = False
    elif args.mechanical_only:
        args.leonardo_direct = False
        args.leonardo_hint = False
    elif args.all:
        args.leonardo_direct = True
        args.leonardo_hint = True
    else:
        # Default: Leonardo direct only
        args.skip_mechanical = True
        args.leonardo_direct = True
        args.leonardo_hint = False

    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
