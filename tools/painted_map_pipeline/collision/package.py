"""Write collision trial artifacts (sprites, TMX, previews) for any mask source."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .derive import DeriveResult, obstacle_mask_to_rgba, walkable_preview
from .emit import (
    tmx_placement_for_chunk,
    write_collision_fragment,
    write_collision_tileset,
    write_preview_map,
    write_result_manifest,
)


def masks_from_derive_result(result: DeriveResult) -> dict[str, np.ndarray]:
    return {
        "obstacle_mask": result.obstacle_mask,
        "walkable_mask": result.walkable_mask,
        "void_mask": result.void_mask,
        "canopy_mask": result.canopy_mask,
    }


def write_collision_package(
    *,
    chunk_dir: Path,
    chunk_id: str,
    painted_path: Path,
    painted_image: Image.Image,
    masks: dict[str, np.ndarray],
    placement: tuple[float, float, float, float],
    layer_name: str = "PaintedCollision",
    variant: str = "mechanical",
    extra_meta: dict[str, Any] | None = None,
    preview_map: bool = True,
    tile_size: int = 550,
    preview_margin: int = 550,
) -> dict[str, Any]:
    chunk_dir.mkdir(parents=True, exist_ok=True)
    image_size = painted_image.size
    obstacle_mask = masks["obstacle_mask"]
    walkable_mask = masks.get("walkable_mask")
    canopy_mask = masks.get("canopy_mask")
    void_mask = masks.get("void_mask")

    obstacle_path = chunk_dir / "collision_sprite.png"
    preview_path = chunk_dir / "walkable_preview.png"
    walkable_path = chunk_dir / "walkable_mask.png"
    canopy_path = chunk_dir / "canopy_mask.png"

    obstacle_mask_to_rgba(obstacle_mask).save(obstacle_path)

    pseudo = DeriveResult(
        obstacle_mask=obstacle_mask,
        walkable_mask=walkable_mask if walkable_mask is not None else ~obstacle_mask,
        void_mask=void_mask if void_mask is not None else np.zeros(obstacle_mask.shape, dtype=bool),
        canopy_mask=canopy_mask if canopy_mask is not None else np.zeros(obstacle_mask.shape, dtype=bool),
        cell_size=0,
    )
    walkable_preview(painted_image, pseudo).save(preview_path)
    Image.fromarray((pseudo.walkable_mask.astype("uint8") * 255), mode="L").save(walkable_path)
    Image.fromarray((pseudo.canopy_mask.astype("uint8") * 255), mode="L").save(canopy_path)

    tsx_path = chunk_dir / "collision.tsx"
    write_collision_tileset(tsx_path, obstacle_path, image_size)
    fragment_path = chunk_dir / "collision_layer.fragment.xml"
    write_collision_fragment(
        fragment_path,
        layer_name=layer_name,
        x=placement[0],
        y=placement[1],
        width=placement[2],
        height=placement[3],
        gid=1,
    )

    preview_map_path = None
    if preview_map:
        preview_map_path = chunk_dir / "preview_map.tmx"
        write_preview_map(
            preview_map_path,
            map_width_px=int(placement[0] + placement[2] + preview_margin),
            map_height_px=int(placement[1] + placement[3] + preview_margin),
            tile_size=tile_size,
            painted_image=painted_path,
            painted_placement=placement,
            collision_tsx=tsx_path,
            collision_placement=placement,
            collision_gid=1,
        )

    content = ~pseudo.void_mask if void_mask is not None else np.ones(obstacle_mask.shape, dtype=bool)
    stats = {
        "void_ratio": float(pseudo.void_mask.mean()),
        "obstacle_ratio": float(obstacle_mask[content].mean()) if content.any() else 0.0,
        "walkable_ratio": float(pseudo.walkable_mask[content].mean()) if content.any() else 0.0,
        "canopy_ratio": float(pseudo.canopy_mask[content].mean()) if content.any() else 0.0,
    }

    payload = {
        "chunk_id": chunk_id,
        "variant": variant,
        "painted_image": str(painted_path),
        "tmx_placement": {
            "x": placement[0],
            "y": placement[1],
            "width": placement[2],
            "height": placement[3],
        },
        "layer_name": layer_name,
        "outputs": {
            "collision_sprite": str(obstacle_path),
            "walkable_preview": str(preview_path),
            "walkable_mask": str(walkable_path),
            "canopy_mask": str(canopy_path),
            "collision_tsx": str(tsx_path),
            "collision_fragment": str(fragment_path),
            "preview_map": str(preview_map_path) if preview_map_path else None,
        },
        "derive_stats": stats,
    }
    if extra_meta:
        payload.update(extra_meta)
    write_result_manifest(chunk_dir / "collision_result.json", payload)
    return payload


def build_compare_sheet(variant_dirs: list[tuple[str, Path]], output_path: Path, thumb_max: int = 640) -> None:
    """Stack variant walkable_preview images into one comparison PNG."""
    rows = []
    for label, directory in variant_dirs:
        preview = directory / "walkable_preview.png"
        if not preview.exists():
            continue
        with Image.open(preview) as img:
            img = img.convert("RGB")
            scale = min(1.0, thumb_max / max(img.width, img.height))
            if scale < 1.0:
                img = img.resize(
                    (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                    Image.LANCZOS,
                )
            rows.append((label, img))

    if not rows:
        return

    label_h = 28
    total_h = sum(img.height + label_h for _, img in rows)
    max_w = max(img.width for _, img in rows)
    sheet = Image.new("RGB", (max_w, total_h), (24, 24, 24))
    y = 0
    for label, img in rows:
        sheet.paste(img, (0, y + label_h))
        y += img.height + label_h

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    meta = {"variants": [label for label, _ in rows], "output": str(output_path)}
    output_path.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
