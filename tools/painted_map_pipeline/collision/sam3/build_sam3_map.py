"""Build expanse map.tmx from painted chunks + SAM3 obstacle polygons."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ...insert_chunks import insert_painted_chunks
from ..build_clean_expanse_map import write_empty_shell
from .merge_polygon_obstacles import merge_polygon_obstacles
from .roboflow_workflow import load_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def build_sam3_map(
    *,
    map_path: Path,
    insert_manifest_path: Path,
    sam3_root: Path,
    tile_size: int = 550,
    layer_name: str = "Objects",
    require_all: bool = False,
) -> dict:
    manifest = json.loads(Path(insert_manifest_path).read_text(encoding="utf-8"))
    grid_world = manifest.get("grid_world_size") or [35392, 23744]
    origin = manifest.get("chunks", [{}])[0].get("world_rect", [77, 78, 5056, 3392])
    world_w = int(origin[0]) + int(grid_world[0])
    world_h = int(origin[1]) + int(grid_world[1])

    map_path = Path(map_path).resolve()
    write_empty_shell(map_path, world_w=world_w, world_h=world_h, tile_size=tile_size)

    painted = insert_painted_chunks(map_path, insert_manifest_path, map_path)
    obstacles = merge_polygon_obstacles(
        map_path=map_path,
        manifest_path=insert_manifest_path,
        sam3_root=sam3_root,
        layer_name=layer_name,
        require_all=require_all,
    )
    return {"map": str(map_path), "painted": painted, "obstacles": obstacles}


def main(argv: list[str] | None = None) -> int:
    repo = _repo_root()
    parser = argparse.ArgumentParser(description="Build map.tmx with PaintedGround + SAM3 Objects layer.")
    parser.add_argument(
        "--map",
        default="levels/Frostreach/expanse/map.tmx",
    )
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
    )
    parser.add_argument(
        "--config",
        default="tools/painted_map_pipeline/collision/sam3/sam3.config.example.json",
    )
    parser.add_argument("--layer-name", default="Objects")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args(argv)

    config = load_config((repo / args.config).resolve())
    sam3_root = Path(config.get("output_dir") or "levels/Frostreach/expanse/export/sam3_obstacle")
    if not sam3_root.is_absolute():
        sam3_root = (repo / sam3_root).resolve()

    result = build_sam3_map(
        map_path=(repo / args.map).resolve(),
        insert_manifest_path=(repo / args.manifest).resolve(),
        sam3_root=sam3_root,
        layer_name=args.layer_name,
        require_all=args.require_all,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
