"""Bootstrap a playable TMX level from a single background PNG.

Creates a level folder with:
- Upscaled background PNG + PaintedGround via insert_chunks
- Gameplay shell (terrain, collision, spawners, grass, effects) from a template
"""

from __future__ import annotations

import argparse
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from .insert_chunks import insert_painted_chunks
from .slice_chunks import slice_chunks

Image.MAX_IMAGE_PIXELS = None

DEFAULT_SOURCE_PNG = (
    "/home/fresh/.cursor/projects/home-fresh-projects-Pixel-Realm-Combat-Heroes-public/"
    "assets/frostreach_expanse_large_background_concept-a10b374f-f194-4a78-bd33-4df9807e70bc.png"
)


def _resample_filter():
    resampling = getattr(Image, "Resampling", Image)
    # Bilinear is fast enough for 16500x11000 bootstrap; use LANCZOS only for small images.
    return getattr(resampling, "BILINEAR", Image.BILINEAR)


def _write_text(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _copy_if_missing(src: Path, dst: Path):
    if not src.exists():
        raise FileNotFoundError(f"Missing template file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy2(src, dst)


def _make_tile_row(values: list[int], width: int) -> str:
    row = list(values)
    if len(row) < width:
        row.extend([1] * (width - len(row)))
    return ",".join(str(v) for v in row[:width])


def build_bare_shell_tmx(
    output_path: Path,
    *,
    width_tiles: int,
    height_tiles: int,
    tile_size: int,
) -> Path:
    """A shell with nothing in it but open ground, ready for PaintedGround to be inserted.

    ``build_shell_tmx`` writes a Frostreach demo level -- ice walls across the north, a gate,
    scattered rocks, snow-tuft grass zones, slippery ice patches and ice-ghost spawners -- at
    coordinates hardcoded for a 10x7 world of 550px tiles. Dropped into a 33x18 desert none of
    it belongs there or even lands where it was meant to, and it all has to be deleted by hand.

    So a generated map gets this instead: the two tile layers the engine expects, every tile
    open, and no object layers at all beyond the PaintedGround that ``insert_painted_chunks``
    adds afterwards.
    """
    open_ground = ",\n".join(_make_tile_row([1] * width_tiles, width_tiles)
                             for _ in range(height_tiles))
    can_build = ",\n".join(_make_tile_row([0] * width_tiles, width_tiles)
                           for _ in range(height_tiles))
    xml = f"""<?xml version='1.0' encoding='utf-8'?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" renderorder="right-down" width="{width_tiles}" height="{height_tiles}" tilewidth="{tile_size}" tileheight="{tile_size}" infinite="0" nextlayerid="3" nextobjectid="1">
 <tileset firstgid="1" source="frostreach_prototype_tiles.tsx" />
 <tileset firstgid="11" source="../../tmx/can_build_tiles.tsx" />
 <layer id="1" name="Tile Layer 1" width="{width_tiles}" height="{height_tiles}">
  <data encoding="csv">
{open_ground}
</data>
 </layer>
 <layer id="2" name="can_build_layer" width="{width_tiles}" height="{height_tiles}">
  <data encoding="csv">
{can_build}
</data>
 </layer>
</map>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml, encoding="utf-8")
    return output_path


def build_shell_tmx(
    output_path: Path,
    *,
    width_tiles: int = 10,
    height_tiles: int = 7,
    tile_size: int = 550,
) -> Path:
    """Write a Frostreach-style gameplay shell without PaintedGround."""
    world_w = width_tiles * tile_size
    world_h = height_tiles * tile_size

    # North ice wall (rows 0-1 blocked), row 2 gate gap cols 12-17, open snow elsewhere.
    rows: list[list[int]] = []
    for row in range(height_tiles):
        if row <= 1:
            rows.append([4] * width_tiles)
        elif row == 2:
            line = [4] * width_tiles
            gate_start = max(0, width_tiles // 2 - 2)
            gate_end = min(width_tiles, width_tiles // 2 + 2)
            for col in range(gate_start, gate_end):
                line[col] = 1
            rows.append(line)
        else:
            rows.append([1] * width_tiles)

    # A few river / lake tiles (tile 3) — rough match to concept water blobs.
    water_spots = [
        (4, 2, 2, 1),
        (4, 7, 2, 1),
        (5, 5, 2, 1),
    ]
    for row, col, w, h in water_spots:
        for dy in range(h):
            for dx in range(w):
                r, c = row + dy, col + dx
                if 0 <= r < height_tiles and 0 <= c < width_tiles:
                    rows[r][c] = 3

    tile_csv = ",\n".join(_make_tile_row(r, width_tiles) for r in rows)
    can_build_csv = ",\n".join(_make_tile_row([0] * width_tiles, width_tiles) for _ in range(height_tiles))

    def wall_objects(start_id: int) -> tuple[str, int]:
        parts = []
        oid = start_id
        for col in range(width_tiles):
            for y_tile in (0, 1):
                x = col * tile_size
                y = y_tile * tile_size
                parts.append(
                    f'  <object id="{oid}" gid="5" x="{x}" y="{y}" width="{tile_size}" height="{tile_size}" />'
                )
                oid += 1
        # Gate pillars
        gate_col = max(0, width_tiles // 2 - 3)
        for col in (gate_col, gate_col + 5):
            if 0 <= col < width_tiles:
                x = col * tile_size
                parts.append(
                    f'  <object id="{oid}" gid="9" x="{x}" y="{2 * tile_size}" width="{tile_size}" height="{tile_size}" />'
                )
                oid += 1
        # Scattered rock obstacles
        rock_cols = [2, 4, 7, 8]
        rock_rows = [4, 5, 5, 6]
        for col, row in zip(rock_cols, rock_rows):
            gid = 7 if col % 2 == 0 else 8
            parts.append(
                f'  <object id="{oid}" gid="{gid}" x="{col * tile_size}" y="{row * tile_size}" '
                f'width="{tile_size}" height="{tile_size}" />'
            )
            oid += 1
        return "\n".join(parts), oid

    wall_xml, next_id = wall_objects(1)

    grass_zones = [
        (550, 2200, 1650, 1100, "snow_tufts"),
        (2200, 1100, 1650, 1100, "tundra_sparse"),
        (3300, 3300, 1650, 880, "snow_tufts"),
    ]
    grass_parts = []
    for idx, (x, y, w, h, profile) in enumerate(grass_zones, start=1):
        grass_parts.append(
            f'  <object id="{idx}" x="{x}" y="{y}" width="{w}" height="{h}">\n'
            f'   <properties>\n'
            f'    <property name="grass_profile" value="{profile}" />\n'
            f"   </properties>\n"
            f"  </object>"
        )

    slippery_zones = [
        (440, 880, 1100, 880, 15.0),
        (2200, 2200, 1320, 880, 20.0),
        (4400, 0, 1100, world_h, 10.0),
    ]
    slip_parts = []
    for idx, (x, y, w, h, factor) in enumerate(slippery_zones, start=1):
        slip_parts.append(
            f'  <object id="{idx}" x="{x}" y="{y}" width="{w}" height="{h}">\n'
            f"   <ellipse />\n"
            f"   <properties>\n"
            f'    <property name="slippery_factor" type="float" value="{factor}" />\n'
            f"   </properties>\n"
            f"  </object>"
        )

    spawner_configs = [
        (
            550,
            1100,
            1100,
            1100,
            '{"enemy_spawn_weights":{"ice_ghost":2,"raccoon":1},'
            '"spawn_type":"random_weights","frequency":8,"spawn_number":2,'
            '"spawn_limit":12,"spawn_team_id":"enemy_expanse_west"}',
        ),
        (
            3300,
            2200,
            1100,
            1100,
            '{"enemy_spawn_weights":{"ice_ghost":3,"ice_mage":1},'
            '"spawn_type":"random_weights","frequency":10,"spawn_number":1,'
            '"spawn_limit":8,"spawn_team_id":"enemy_expanse_east"}',
        ),
        (
            2200,
            550,
            1100,
            880,
            '{"enemy_spawn_weights":{"ice_mage":1,"spirit":1},'
            '"spawn_type":"random_weights","frequency":14,"spawn_number":1,'
            '"spawn_limit":4,"spawn_team_id":"enemy_expanse_gate"}',
        ),
        (
            1650,
            3300,
            1650,
            1100,
            '{"enemy_spawn_weights":{"ice_ghost":2,"ice_mage":1,"raccoon":1},'
            '"spawn_type":"random_weights","frequency":12,"spawn_number":3,'
            '"spawn_limit":15,"spawn_team_id":"enemy_expanse_center"}',
        ),
    ]
    spawner_parts = []
    for idx, (x, y, w, h, cfg) in enumerate(spawner_configs, start=1):
        escaped = cfg.replace('"', "&quot;")
        spawner_parts.append(
            f'  <object id="{idx}" x="{x}" y="{y}" width="{w}" height="{h}">\n'
            f"   <properties>\n"
            f'    <property name="spawner_config" value="{escaped}" />\n'
            f"   </properties>\n"
            f"  </object>"
        )

    xml = f"""<?xml version='1.0' encoding='utf-8'?>
<map version="1.10" tiledversion="1.11.0" orientation="orthogonal" renderorder="right-down" width="{width_tiles}" height="{height_tiles}" tilewidth="{tile_size}" tileheight="{tile_size}" infinite="0" nextlayerid="7" nextobjectid="{next_id}">
 <tileset firstgid="1" source="frostreach_prototype_tiles.tsx" />
 <tileset firstgid="11" source="../../tmx/can_build_tiles.tsx" />
 <layer id="1" name="Tile Layer 1" width="{width_tiles}" height="{height_tiles}">
  <data encoding="csv">
{tile_csv}
</data>
 </layer>
 <layer id="2" name="can_build_layer" width="{width_tiles}" height="{height_tiles}">
  <data encoding="csv">
{can_build_csv}
</data>
 </layer>
 <objectgroup id="3" name="Object Layer 1">
{wall_xml}
 </objectgroup>
 <objectgroup id="4" name="grass1">
{chr(10).join(grass_parts)}
 </objectgroup>
 <objectgroup id="5" name="Slippery Effect Layer">
{chr(10).join(slip_parts)}
 </objectgroup>
 <objectgroup id="6" name="spawner">
{chr(10).join(spawner_parts)}
 </objectgroup>
</map>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml, encoding="utf-8")
    return output_path


def bootstrap_level(
    source_png: Path,
    level_dir: Path,
    *,
    width_tiles: int = 10,
    height_tiles: int = 7,
    tile_size: int = 550,
    template_dir: Path | None = None,
    bare: bool = True,
) -> dict:
    source_png = Path(source_png).resolve()
    level_dir = Path(level_dir).resolve()
    template_dir = Path(template_dir or level_dir.parent / "ice_wall_gate").resolve()

    world_w = width_tiles * tile_size
    world_h = height_tiles * tile_size
    generated_dir = level_dir / "generated_bootstrap"
    chunks_dir = generated_dir / "chunks"
    shell_path = level_dir / "shell_outline.tmx"
    map_path = level_dir / "map.tmx"

    level_dir.mkdir(parents=True, exist_ok=True)

    # Sidecar files from Frostreach template.
    for name in (
        "frostreach_prototype_tiles.tsx",
        "frostreach_prototype_tiles.png",
        "grass_profiles.json",
        "layout_general_config.txt",
        "initial_layout_name.txt",
    ):
        _copy_if_missing(template_dir / name, level_dir / name)

    rel_layout = f"../levels/Frostreach/{level_dir.name}"
    _write_text(level_dir / "initial_layout_name.txt", rel_layout + "\n")
    _write_text(level_dir / "layout_general_config.txt", "True\n")

    # Upscale background to standard world size.
    background_path = level_dir / "background.png"
    with Image.open(source_png) as img:
        rgb = img.convert("RGB").resize((world_w, world_h), _resample_filter())
        rgb.save(background_path, optimize=True)

    # bare by default: the demo shell's walls, rocks, grass, ice and spawners are authored for
    # a different world and have to be deleted by hand from every generated map.
    shell = build_bare_shell_tmx if bare else build_shell_tmx
    shell(shell_path, width_tiles=width_tiles, height_tiles=height_tiles, tile_size=tile_size)

    slice_chunks(
        background_path,
        chunks_dir,
        chunk_size=[world_w, world_h],
        overlap=0,
    )
    chunk_dir = chunks_dir / "chunk_00_00"
    shutil.copy2(background_path, chunk_dir / "painted.png")

    insert_result = insert_painted_chunks(shell_path, chunks_dir / "chunks_manifest.json", map_path)

    manifest = {
        "level_slug": level_dir.name,
        "source_png": str(source_png),
        "background_png": str(background_path),
        "world_size_px": [world_w, world_h],
        "shell_tmx": str(shell_path),
        "map_tmx": str(map_path),
        "insert": insert_result,
    }
    _write_text(generated_dir / "bootstrap_summary.json", json.dumps(manifest, indent=2))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bootstrap a TMX level from a single PNG background.")
    parser.add_argument("--source-png", default=DEFAULT_SOURCE_PNG, help="Concept / background PNG path.")
    parser.add_argument(
        "--level-dir",
        default="../../levels/Frostreach/expanse",
        help="Output level folder (contains map.tmx).",
    )
    parser.add_argument("--template-dir", default="../../levels/Frostreach/ice_wall_gate")
    parser.add_argument("--width-tiles", type=int, default=10)
    parser.add_argument("--height-tiles", type=int, default=7)
    parser.add_argument("--tile-size", type=int, default=550)
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parent
    level_dir = (base / args.level_dir).resolve()
    template_dir = (base / args.template_dir).resolve()
    source_png = Path(args.source_png).resolve()

    result = bootstrap_level(
        source_png,
        level_dir,
        template_dir=template_dir,
        width_tiles=args.width_tiles,
        height_tiles=args.height_tiles,
        tile_size=args.tile_size,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
