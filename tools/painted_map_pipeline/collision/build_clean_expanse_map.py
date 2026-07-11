"""Build a clean expanse map.tmx from existing painted + collision chunk PNGs only."""

from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

from ..insert_chunks import insert_painted_chunks
from .merge_collision_grid import merge_collision_grid
from .verify_map_jigsaw import verify_map_jigsaw
from .variant_paths import DEFAULT_LEONARDO_VARIANT


def write_empty_shell(map_path: Path, *, world_w: int, world_h: int, tile_size: int = 550) -> None:
    cols = max(1, int(math.ceil(world_w / tile_size)))
    rows = max(1, int(math.ceil(world_h / tile_size)))
    root = ET.Element(
        "map",
        {
            "version": "1.8",
            "tiledversion": "1.8.0",
            "orientation": "orthogonal",
            "renderorder": "right-down",
            "width": str(cols),
            "height": str(rows),
            "tilewidth": str(tile_size),
            "tileheight": str(tile_size),
            "infinite": "0",
            "nextlayerid": "2",
            "nextobjectid": "1",
        },
    )
    ET.indent(root, space=" ")
    map_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(map_path, encoding="utf-8", xml_declaration=True)


def build_clean_expanse_map(
    *,
    map_path: Path,
    insert_manifest_path: Path,
    collision_trial_root: Path,
    tile_size: int = 550,
    variant_subdir: str = DEFAULT_LEONARDO_VARIANT,
) -> dict:
    manifest = json.loads(Path(insert_manifest_path).read_text(encoding="utf-8"))
    grid_world = manifest.get("grid_world_size") or [35392, 23744]
    origin = manifest.get("chunks", [{}])[0].get("world_rect", [77, 78, 5056, 3392])
    world_w = int(origin[0]) + int(grid_world[0])
    world_h = int(origin[1]) + int(grid_world[1])

    map_path = Path(map_path).resolve()
    write_empty_shell(map_path, world_w=world_w, world_h=world_h, tile_size=tile_size)

    painted = insert_painted_chunks(map_path, insert_manifest_path, map_path)
    collision = merge_collision_grid(
        map_path=map_path,
        manifest_path=insert_manifest_path,
        collision_trial_root=collision_trial_root,
        variant_subdir=variant_subdir,
        require_all=True,
    )
    verify = verify_map_jigsaw(
        map_path=map_path,
        manifest_path=insert_manifest_path,
        collision_trial_root=collision_trial_root,
        variant_subdir=variant_subdir,
    )
    if not verify["ok"]:
        raise RuntimeError(
            f"Jigsaw verification failed; see {verify.get('report_json')} and "
            f"{verify.get('review_artifact')}"
        )
    return {"map": str(map_path), "painted": painted, "collision": collision, "verify": verify}


def main(argv: list[str] | None = None) -> int:
    repo = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="Rebuild clean expanse map from existing chunk PNGs.")
    parser.add_argument(
        "--map",
        default="levels/Frostreach/expanse/map_visual.tmx",
        help="Output TMX (default map_visual.tmx — does not overwrite playable map.tmx).",
    )
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
    )
    parser.add_argument(
        "--collision-trial",
        default="levels/Frostreach/expanse/export/collision_trial",
    )
    parser.add_argument(
        "--variant-subdir",
        default=DEFAULT_LEONARDO_VARIANT,
        help=f"Trial subfolder per chunk (default: {DEFAULT_LEONARDO_VARIANT})",
    )
    args = parser.parse_args(argv)

    result = build_clean_expanse_map(
        map_path=(repo / args.map).resolve(),
        insert_manifest_path=(repo / args.manifest).resolve(),
        collision_trial_root=(repo / args.collision_trial).resolve(),
        variant_subdir=args.variant_subdir,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
