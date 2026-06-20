from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw


DEFAULT_STYLE_PROMPT = (
    "Polish this rough TMX chunk into a coherent top-down / slightly 2.5D pixel RPG "
    "painted ground background. Preserve the layout exactly: exits, road directions, "
    "water/ice/cliff positions, broad walkable spaces, and obstacle silhouettes must "
    "remain aligned with the source. Treat source.png as a production map, not a loose "
    "concept sketch: do not invent new cliffs, trees, buildings, canyons, or large props. "
    "Keep the camera flatter than isometric, preserve large empty snow/ice fields when the "
    "source is sparse, and keep scale consistent with player-sized sprites. Improve terrain "
    "detail, natural transitions, snow/ice texture, cliff readability, and overall production "
    "quality. Do not add UI, labels, text, grid lines, giant props, or objects that would "
    "invalidate collision. Keep paths 2-4 character widths and keep edges continuous with "
    "neighboring chunks."
)


def _copy_reference(src, dst_dir, name):
    if not src:
        return None
    src_path = Path(src)
    if not src_path.exists():
        return None
    dst = dst_dir / name
    shutil.copy2(src_path, dst)
    return str(dst)


def _is_generated_painted(chunk: dict):
    painted_path = Path(chunk["painted_image"])
    if not painted_path.exists():
        return False
    result_path = painted_path.parent / "context" / "image_result.json"
    if not result_path.exists():
        return False
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    provider = str(result.get("provider", "")).strip().lower()
    return provider in {"cursor_agent_image_tool", "external_agent_image", "manual_agent_image"}


def _copy_neighbor_references(metadata: dict, chunk_lookup: dict, context_dir: Path):
    references = {}
    for direction, neighbor_id in sorted(metadata.get("neighbors", {}).items()):
        neighbor = chunk_lookup.get(neighbor_id)
        if not neighbor:
            continue

        if _is_generated_painted(neighbor):
            src = Path(neighbor["painted_image"])
            status = "painted"
        else:
            src = Path(neighbor["source_image"])
            status = "source"

        if not src.exists():
            continue

        filename = f"neighbor_{direction}_{status}.png"
        dst = context_dir / filename
        shutil.copy2(src, dst)
        references[direction] = {
            "chunk_id": neighbor_id,
            "status": status,
            "path": str(dst),
            "filename": filename,
        }
    return references


def _fit_size(width: int, height: int, max_size: int):
    scale = min(max_size / max(width, height), 1.0)
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _resize_for_preview(image: Image.Image, max_size: int):
    size = _fit_size(image.width, image.height, max_size)
    if image.size == size:
        return image.copy()
    resampling = getattr(Image, "Resampling", Image)
    return image.resize(size, getattr(resampling, "LANCZOS", Image.BICUBIC))


def _build_chunk_locator(full_image_path, metadata: dict, context_dir: Path):
    if not full_image_path:
        return None
    full_image_path = Path(full_image_path)
    if not full_image_path.exists():
        return None

    with Image.open(full_image_path) as image:
        image = image.convert("RGBA")
        full_w, full_h = image.size
        preview = _resize_for_preview(image, 1400)

    scale_x = preview.width / full_w
    scale_y = preview.height / full_h
    x, y, w, h = metadata.get("world_rect", metadata.get("source_rect_with_overlap"))
    rect = [
        int(round(x * scale_x)),
        int(round(y * scale_y)),
        int(round((x + w) * scale_x)),
        int(round((y + h) * scale_y)),
    ]
    overlay = Image.new("RGBA", preview.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle(rect, outline=(255, 40, 40, 255), width=6)
    draw.rectangle(rect, fill=(255, 40, 40, 55))
    preview = Image.alpha_composite(preview, overlay)

    path = context_dir / "chunk_locator.png"
    preview.save(path)
    return str(path)


def _load_preview_image(path: str | Path, max_size: int):
    with Image.open(path) as image:
        return _resize_for_preview(image.convert("RGBA"), max_size)


def _text_size(draw: ImageDraw.ImageDraw, text: str):
    try:
        box = draw.textbbox((0, 0), text)
        return box[2] - box[0], box[3] - box[1]
    except ValueError:
        return draw.textsize(text)


def _build_local_neighborhood(metadata: dict, source_path: Path, neighbor_refs: dict, context_dir: Path):
    max_cell = 520
    gap = 12
    bg = (18, 26, 34, 255)
    label_bg = (0, 0, 0, 130)
    label_fg = (255, 255, 255, 255)

    entries = {
        "current": {
            "label": f"current {metadata['chunk_id']} source",
            "path": source_path,
        }
    }
    for direction, ref in neighbor_refs.items():
        entries[direction] = {
            "label": f"{direction} {ref['chunk_id']} {ref['status']}",
            "path": ref["path"],
        }

    loaded = {
        key: {
            "label": value["label"],
            "image": _load_preview_image(value["path"], max_cell),
        }
        for key, value in entries.items()
    }
    cell_w = max(item["image"].width for item in loaded.values())
    cell_h = max(item["image"].height for item in loaded.values())
    canvas = Image.new("RGBA", (cell_w * 3 + gap * 2, cell_h * 3 + gap * 2), bg)
    draw = ImageDraw.Draw(canvas)
    positions = {
        "north": (1, 0),
        "west": (0, 1),
        "current": (1, 1),
        "east": (2, 1),
        "south": (1, 2),
    }

    for key, item in loaded.items():
        col, row = positions.get(key, (1, 1))
        cell_x = col * (cell_w + gap)
        cell_y = row * (cell_h + gap)
        image = item["image"]
        x = cell_x + (cell_w - image.width) // 2
        y = cell_y + (cell_h - image.height) // 2
        canvas.alpha_composite(image, (x, y))
        label = item["label"]
        text_w, text_h = _text_size(draw, label)
        draw.rectangle((x, y, x + text_w + 10, y + text_h + 8), fill=label_bg)
        draw.text((x + 5, y + 4), label, fill=label_fg)

    path = context_dir / "local_neighborhood.png"
    canvas.save(path)
    return str(path)


def _neighbor_prompt_lines(neighbor_refs: dict):
    if not neighbor_refs:
        return ["Attached neighbor images: none for this edge chunk."]
    lines = ["Attached neighbor images:"]
    for direction, ref in sorted(neighbor_refs.items()):
        lines.append(
            f"- {ref['filename']}: {direction} neighbor {ref['chunk_id']} "
            f"({ref['status']}; use only for shared-edge continuity)."
        )
    return lines


def build_prompt(metadata, config, references=None):
    style_prompt = config.get("style_prompt") or DEFAULT_STYLE_PROMPT
    region_name = config.get("region_name", "Unknown Region")
    chunk_role = config.get("chunk_roles", {}).get(metadata["chunk_id"], "")
    neighbors = metadata.get("neighbors", {})
    references = references or {}
    neighbor_refs = references.get("neighbors", {})
    has_local_neighborhood = bool(references.get("local_neighborhood"))
    local_neighborhood_line = (
        "- local_neighborhood.png shows current source plus available neighbor images."
        if has_local_neighborhood
        else "- local_neighborhood.png is optional and was not generated for this pack."
    )
    return "\n".join(
        [
            style_prompt,
            "",
            f"Region: {region_name}",
            f"Chunk ID: {metadata['chunk_id']}",
            f"Chunk role: {chunk_role or 'Preserve the rough source layout and local transitions.'}",
            f"World rect: {metadata['world_rect']}",
            f"Source rect including overlap: {metadata['source_rect_with_overlap']}",
            f"Neighbors: {json.dumps(neighbors, sort_keys=True)}",
            "",
            "Location/continuity images:",
            "- chunk_locator.png shows where this chunk sits in the full rough map.",
            local_neighborhood_line,
            *_neighbor_prompt_lines(neighbor_refs),
            "",
            "Input image priorities:",
            "1. source.png is the exact layout to preserve.",
            "2. neighbor_* images guide only shared-edge continuity.",
            "3. chunk_locator.png gives map position; do not invent a new composition from it.",
            "4. world_map_reference.png gives macro geography.",
            "5. region_reference.png gives local biome/style direction.",
            "6. asset_contact_sheet.png gives game scale and asset vibe.",
            "",
            "Scale rule: source.png is a reduced working image for generation, while the chunk",
            "metadata records the larger world/map rectangle it will cover in TMX.",
            "",
            "Critical rule: do not copy a neighbor's full composition into this chunk. Continue the",
            "shared edge while preserving this chunk's own source.png geometry.",
            "",
            "Output a single polished painted background PNG for this chunk.",
        ]
    )


def build_context_packs(chunks_manifest, output_dir, config, asset_contact_sheet=None, chunk_ids=None):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunk_lookup = {chunk["chunk_id"]: chunk for chunk in chunks_manifest["chunks"]}
    chunk_ids = set(chunk_ids or [])
    chunks_to_build = [
        chunk for chunk in chunks_manifest["chunks"] if not chunk_ids or chunk["chunk_id"] in chunk_ids
    ]
    packs = []
    for metadata in chunks_to_build:
        chunk_id = metadata["chunk_id"]
        chunk_dir = Path(metadata["source_image"]).parent
        context_dir = chunk_dir / "context"
        context_dir.mkdir(parents=True, exist_ok=True)

        (context_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        source_context_path = context_dir / "source.png"
        shutil.copy2(metadata["source_image"], source_context_path)
        neighbor_refs = _copy_neighbor_references(metadata, chunk_lookup, context_dir)
        locator_path = _build_chunk_locator(chunks_manifest.get("source_image"), metadata, context_dir)
        local_neighborhood_path = None
        if bool(config.get("build_local_neighborhood", False)):
            local_neighborhood_path = _build_local_neighborhood(
                metadata,
                source_context_path,
                neighbor_refs,
                context_dir,
            )

        references = {
            "source": str(source_context_path),
            "world_map_reference": _copy_reference(
                config.get("world_reference"), context_dir, "world_map_reference.png"
            ),
            "region_reference": _copy_reference(
                config.get("region_reference"), context_dir, "region_reference.png"
            ),
            "asset_contact_sheet": _copy_reference(
                asset_contact_sheet, context_dir, "asset_contact_sheet.png"
            ),
            "chunk_locator": locator_path,
            "local_neighborhood": local_neighborhood_path,
            "neighbors": neighbor_refs,
        }
        prompt = build_prompt(metadata, config, references)
        (context_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

        packs.append(
            {
                "chunk_id": chunk_id,
                "context_dir": str(context_dir),
                "prompt_path": str(context_dir / "prompt.txt"),
                "references": references,
                "painted_image": metadata["painted_image"],
            }
        )

    manifest = {"packs": packs}
    (output_dir / "context_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest

