"""CLI: derive collision for a single painted chunk."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from .derive import (
    DeriveConfig,
    derive_collision_masks,
    obstacle_mask_to_rgba,
    walkable_preview,
)
from .emit import (
    chunk_entry,
    load_manifest,
    tmx_placement_for_chunk,
    write_collision_fragment,
    write_collision_tileset,
    write_preview_map,
    write_result_manifest,
)


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_config(path: Path | None) -> DeriveConfig:
    if path is None or not path.exists():
        return DeriveConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    derive_section = data.get("derive", data)
    return DeriveConfig.from_mapping(derive_section)


def run(args: argparse.Namespace) -> Path:
    repo = _default_repo_root()
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = (repo / manifest_path).resolve()

    manifest = load_manifest(manifest_path)
    chunk = chunk_entry(manifest, args.chunk)
    painted_path = Path(chunk["painted_image"])
    if not painted_path.is_absolute():
        painted_path = (repo / painted_path).resolve()
    if not painted_path.exists():
        raise FileNotFoundError(painted_path)

    reference_tmx = Path(args.reference_tmx) if args.reference_tmx else None
    if reference_tmx is not None and not reference_tmx.is_absolute():
        reference_tmx = (repo / reference_tmx).resolve()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = (repo / output_dir).resolve()
    chunk_dir = output_dir / args.chunk
    chunk_dir.mkdir(parents=True, exist_ok=True)

    config = _load_config(Path(args.config) if args.config else chunk_dir / "derive.config.json")
    if args.write_default_config and not (chunk_dir / "derive.config.json").exists():
        default = {
            "derive": DeriveConfig().__dict__,
            "notes": "Tune luminance thresholds, re-run run_chunk.py. Red=obstacle, green=walkable in preview.",
        }
        (chunk_dir / "derive.config.json").write_text(json.dumps(default, indent=2) + "\n", encoding="utf-8")

    with Image.open(painted_path) as painted:
        result = derive_collision_masks(painted, config)
        preview = walkable_preview(painted, result)
        obstacle_rgba = obstacle_mask_to_rgba(result.obstacle_mask)
        image_size = painted.size

    obstacle_path = chunk_dir / "collision_sprite.png"
    preview_path = chunk_dir / "walkable_preview.png"
    walkable_path = chunk_dir / "walkable_mask.png"
    canopy_path = chunk_dir / "canopy_mask.png"
    obstacle_rgba.save(obstacle_path)
    preview.save(preview_path)
    Image.fromarray((result.walkable_mask.astype("uint8") * 255), mode="L").save(walkable_path)
    Image.fromarray((result.canopy_mask.astype("uint8") * 255), mode="L").save(canopy_path)

    placement = tmx_placement_for_chunk(chunk, manifest, reference_tmx=reference_tmx)
    tsx_path = chunk_dir / "collision.tsx"
    write_collision_tileset(tsx_path, obstacle_path, image_size)

    fragment_path = chunk_dir / "collision_layer.fragment.xml"
    write_collision_fragment(
        fragment_path,
        layer_name=args.layer_name,
        x=placement[0],
        y=placement[1],
        width=placement[2],
        height=placement[3],
        gid=1,
    )

    if args.preview_map:
        map_path = chunk_dir / "preview_map.tmx"
        margin = int(args.preview_margin)
        px, py = placement[0], placement[1]
        pw, ph = placement[2], placement[3]
        write_preview_map(
            map_path,
            map_width_px=int(px + pw + margin),
            map_height_px=int(py + ph + margin),
            tile_size=int(args.tile_size),
            painted_image=painted_path,
            painted_placement=placement,
            collision_tsx=tsx_path,
            collision_placement=placement,
            collision_gid=1,
        )

    payload = {
        "chunk_id": args.chunk,
        "painted_image": str(painted_path),
        "manifest": str(manifest_path),
        "reference_tmx": str(reference_tmx) if reference_tmx else None,
        "tmx_placement": {
            "x": placement[0],
            "y": placement[1],
            "width": placement[2],
            "height": placement[3],
        },
        "layer_name": args.layer_name,
        "outputs": {
            "collision_sprite": str(obstacle_path),
            "walkable_preview": str(preview_path),
            "walkable_mask": str(walkable_path),
            "canopy_mask": str(canopy_path),
            "collision_tsx": str(tsx_path),
            "collision_fragment": str(fragment_path),
            "preview_map": str(chunk_dir / "preview_map.tmx") if args.preview_map else None,
        },
        "derive_stats": result.stats,
        "derive_config": config.__dict__,
    }
    write_result_manifest(chunk_dir / "collision_result.json", payload)
    return chunk_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive a PaintedCollision object-layer sprite for one painted chunk."
    )
    parser.add_argument("--chunk", required=True, help="Chunk id, e.g. chunk_06_06")
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
        help="insert_manifest.json or grid_manifest.json with chunk entries",
    )
    parser.add_argument(
        "--reference-tmx",
        default="levels/Frostreach/expanse/map.tmx",
        help="Map used to align chunk x/y with PaintedGround (recommended)",
    )
    parser.add_argument(
        "--output-dir",
        default="levels/Frostreach/expanse/export/collision_trial",
        help="Output root; one subfolder per chunk",
    )
    parser.add_argument("--config", help="Optional derive.config.json (defaults written on first run)")
    parser.add_argument(
        "--layer-name",
        default="PaintedCollision",
        help="TMX object layer name (engine treats non-PaintedGround image layers as obstacles)",
    )
    parser.add_argument("--preview-map", action="store_true", help="Write preview_map.tmx for Tiled review")
    parser.add_argument("--preview-margin", type=int, default=550)
    parser.add_argument("--tile-size", type=int, default=550)
    parser.add_argument("--write-default-config", action="store_true")
    args = parser.parse_args(argv)

    out = run(args)
    print(f"Wrote collision trial outputs to {out}")
    print(f"  preview: {out / 'walkable_preview.png'}")
    print(f"  sprite:  {out / 'collision_sprite.png'}")
    print(f"  fragment:{out / 'collision_layer.fragment.xml'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
