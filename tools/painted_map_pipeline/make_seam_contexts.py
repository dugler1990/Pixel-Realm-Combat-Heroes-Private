from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

from .assemble_preview import build_assembled_image, load_manifest, save_preview_image

Image.MAX_IMAGE_PIXELS = None


def _resample_filter():
    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS", Image.BICUBIC)


def _chunk_rect(chunk: dict):
    return [int(v) for v in chunk.get("source_rect_with_overlap", chunk["world_rect"])]


def _rect_intersection(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    if right <= left or bottom <= top:
        return None
    return [left, top, right - left, bottom - top]


def _affected_chunks(manifest: dict, rect):
    affected = []
    for chunk in manifest.get("chunks", []):
        overlap = _rect_intersection(rect, _chunk_rect(chunk))
        if overlap:
            affected.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "chunk_rect": _chunk_rect(chunk),
                    "overlap_rect": overlap,
                    "painted_image": chunk["painted_image"],
                }
            )
    return affected


def _clamp_rect_from_center(center_x: int, center_y: int, width: int, height: int, full_w: int, full_h: int):
    left = max(0, min(full_w - width, int(round(center_x - width / 2))))
    top = max(0, min(full_h - height, int(round(center_y - height / 2))))
    return [left, top, min(width, full_w - left), min(height, full_h - top)]


def _endpoint_for_side(side: str, width: int, height: int):
    side = side.lower()
    if side == "north":
        return {"side": side, "point": [width // 2, 0], "label": "road endpoint must connect"}
    if side == "south":
        return {"side": side, "point": [width // 2, height - 1], "label": "road endpoint must connect"}
    if side == "west":
        return {"side": side, "point": [0, height // 2], "label": "road endpoint must connect"}
    if side == "east":
        return {"side": side, "point": [width - 1, height // 2], "label": "road endpoint must connect"}
    raise ValueError(f"Unknown connection side: {side}")


def _endpoints_from_connections(connections: list[str], width: int, height: int):
    endpoints = []
    seen = set()
    for connection in connections:
        parts = [part.strip().lower() for part in connection.split("_to_")]
        if len(parts) != 2:
            continue
        for side in parts:
            if side in seen:
                continue
            endpoint = _endpoint_for_side(side, width, height)
            endpoints.append(endpoint)
            seen.add(side)
    return endpoints


def _draw_source_annotation(source: Image.Image, patch: dict):
    annotated = source.convert("RGBA")
    draw = ImageDraw.Draw(annotated)
    endpoints = patch.get("endpoints", [])
    connections = patch.get("connections", [])
    width, height = source.size

    for endpoint in endpoints:
        x, y = endpoint["point"]
        radius = max(18, min(width, height) // 40)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=(255, 0, 0, 255), width=6)
        label_x = max(8, min(width - 240, x + 12))
        label_y = max(8, min(height - 24, y + 12))
        draw.text((label_x, label_y), endpoint.get("label", "must connect"), fill=(255, 0, 0, 255))

    for connection in connections:
        parts = [part.strip().lower() for part in connection.split("_to_")]
        if len(parts) != 2:
            continue
        try:
            start = _endpoint_for_side(parts[0], width, height)["point"]
            end = _endpoint_for_side(parts[1], width, height)["point"]
        except ValueError:
            continue
        draw.line((start[0], start[1], end[0], end[1]), fill=(255, 0, 0, 255), width=5)

    if not endpoints:
        draw.rectangle((8, 8, width - 9, height - 9), outline=(255, 0, 0, 255), width=6)
        draw.text((24, 24), "inspect seam continuity", fill=(255, 0, 0, 255))
    return annotated


def _highlight_context(assembled: Image.Image, rect, output_path: Path, max_width: int):
    if assembled.width > max_width:
        scale = max_width / assembled.width
        preview = assembled.resize(
            (max_width, max(1, int(round(assembled.height * scale)))),
            _resample_filter(),
        )
    else:
        scale = 1
        preview = assembled.copy()
    draw = ImageDraw.Draw(preview)
    x, y, w, h = rect
    scaled_rect = (
        int(round(x * scale)),
        int(round(y * scale)),
        int(round((x + w) * scale)) - 1,
        int(round((y + h) * scale)) - 1,
    )
    draw.rectangle(scaled_rect, outline=(255, 0, 0, 255), width=max(2, int(24 * scale)))
    preview.save(output_path)


def _prompt_for_patch(patch_id: str, kind: str, rect, affected, repair_goal: str, connections: list[str], notes: str):
    affected_ids = ", ".join(item["chunk_id"] for item in affected)
    semantic_lines = [
        "Primary task: repair semantic continuity across generated chunk boundaries.",
        "Do not merely blur or blend texture. Redraw the broken feature so it logically connects.",
    ]
    if repair_goal == "connect_walkway":
        semantic_lines = [
            "Primary task: reconstruct the grey walkable road/path so the visible endpoints connect across this seam.",
            "The road must read as one continuous traversable route, not separate generated fragments.",
            "Do not merely blur or blend texture. Redraw the path connection.",
        ]
    elif repair_goal == "connect_ice_river":
        semantic_lines = [
            "Primary task: reconnect the ice/water shape so the flow reads as one continuous feature.",
            "Do not merely blur or blend texture. Redraw the river/ice edge connection.",
        ]
    elif repair_goal == "align_cliff":
        semantic_lines = [
            "Primary task: align cliff/wall edges so the terrain structure continues across the seam.",
            "Do not merely blur or blend texture. Redraw the cliff/wall continuation.",
        ]

    connection_lines = []
    if connections:
        connection_lines = [
            "Required endpoint connections:",
            *[f"- {connection.replace('_', ' ')}" for connection in connections],
        ]
    if notes:
        connection_lines.extend(["Repair notes:", notes])

    return "\n".join(
        [
            f"Repair the map continuity in patch {patch_id}.",
            "",
            f"Patch type: {kind}",
            f"Repair goal: {repair_goal}",
            f"Global crop rect: {rect}",
            f"Affected chunks: {affected_ids}",
            "",
            "Use source.png as the exact patch to repair.",
            "Use source_annotated.png to understand which visible endpoints/features must connect.",
            "Use context_full.png only to understand where the patch sits in the full map.",
            "",
            *semantic_lines,
            *connection_lines,
            "",
            "Fix visible seam issues only: roads/path continuity, ice/water flow, cliff continuity,",
            "and then texture blending around the repaired feature.",
            "Preserve the outer edges of this crop so it can be pasted back into the map.",
            "Do not add UI, labels, characters, buildings, or new blocking structures.",
            "Output a single fixed image with the same composition and aspect ratio as source.png.",
        ]
    )


def _repair_goal_for_feature(feature_type: str):
    mapping = {
        "road": "connect_walkway",
        "walkway": "connect_walkway",
        "path": "connect_walkway",
        "river": "connect_ice_river",
        "ice": "connect_ice_river",
        "water": "connect_ice_river",
        "cliff": "align_cliff",
        "wall": "align_cliff",
        "texture": "blend_texture",
    }
    return mapping.get((feature_type or "").lower(), "inspect_continuity")


def _patch_from_issue(issue: dict, manifest: dict):
    rect = [int(v) for v in issue["global_rect"]]
    w, h = rect[2], rect[3]
    connections = issue.get("connections", [])
    repair_goal = issue.get("repair_goal") or _repair_goal_for_feature(issue.get("feature_type", ""))
    notes = issue.get("expected_fix") or issue.get("problem", "")
    patch_id = issue.get("patch_id") or issue["issue_id"]
    return {
        "patch_id": patch_id,
        "kind": "issue_targeted",
        "rect": rect,
        "repair_goal": repair_goal,
        "connections": connections,
        "endpoints": _endpoints_from_connections(connections, w, h),
        "notes": notes,
        "issue_id": issue["issue_id"],
    }


def _write_patch(output_dir: Path, patch: dict, assembled: Image.Image, manifest: dict, max_context_width: int):
    patch_dir = output_dir / "patches" / patch["patch_id"]
    patch_dir.mkdir(parents=True, exist_ok=True)
    rect = patch["rect"]
    x, y, w, h = rect

    source = assembled.crop((x, y, x + w, y + h))
    source_path = patch_dir / "source.png"
    source.save(source_path)

    annotated_path = patch_dir / "source_annotated.png"
    _draw_source_annotation(source, patch).save(annotated_path)

    context_path = patch_dir / "context_full.png"
    _highlight_context(assembled, rect, context_path, max_context_width)

    affected = _affected_chunks(manifest, rect)
    repair_goal = patch.get("repair_goal", "inspect_continuity")
    connections = patch.get("connections", [])
    notes = patch.get("notes", "")
    metadata = {
        "patch_id": patch["patch_id"],
        "kind": patch["kind"],
        "issue_id": patch.get("issue_id"),
        "repair_goal": repair_goal,
        "connections": connections,
        "endpoints": patch.get("endpoints", []),
        "notes": notes,
        "global_rect": rect,
        "patch_size": [w, h],
        "affected_chunks": affected,
        "source": str(source_path),
        "source_annotated": str(annotated_path),
        "context_full": str(context_path),
    }
    metadata_path = patch_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    prompt_path = patch_dir / "prompt.txt"
    prompt_path.write_text(
        _prompt_for_patch(patch["patch_id"], patch["kind"], rect, affected, repair_goal, connections, notes),
        encoding="utf-8",
    )
    return metadata


def _parse_target_spec(raw: str, manifest: dict, default_patch_size: int):
    values = {}
    for part in raw.split(","):
        if "=" not in part:
            raise ValueError(f"Invalid target spec part: {part}")
        key, value = part.split("=", 1)
        values[key.strip()] = value.strip()

    full_w, full_h = [int(v) for v in manifest["image_size"]]
    patch_id = values.get("id", "targeted_semantic_patch")
    center_raw = values.get("center")
    if not center_raw:
        raise ValueError("Target spec requires center=x:y")
    center_x, center_y = [int(v) for v in center_raw.replace("x", ":").split(":", 1)]

    size_raw = values.get("size", f"{default_patch_size}x{default_patch_size}")
    width, height = [int(v) for v in size_raw.replace(":", "x").split("x", 1)]
    connections = [
        item.strip()
        for item in values.get("connections", "").replace("|", ";").split(";")
        if item.strip()
    ]
    rect = _clamp_rect_from_center(center_x, center_y, width, height, full_w, full_h)
    width, height = rect[2], rect[3]
    return {
        "patch_id": patch_id,
        "kind": "targeted",
        "rect": rect,
        "repair_goal": values.get("goal", "connect_walkway"),
        "connections": connections,
        "endpoints": _endpoints_from_connections(connections, width, height),
        "notes": values.get("notes", ""),
    }


def _build_patch_specs(manifest: dict, patch_size: int):
    full_w, full_h = [int(v) for v in manifest["image_size"]]
    cols, rows = [int(v) for v in manifest["grid_size"]]
    chunk_w, chunk_h = [int(v) for v in manifest["world_chunk_size"]]
    half = patch_size // 2
    patches = []

    for col in range(1, cols):
        x = col * chunk_w
        left = max(0, x - half)
        right = min(full_w, x + half)
        patches.append(
            {
                "patch_id": f"vertical_col_{col - 1}_{col}",
                "kind": "vertical",
                "rect": [left, 0, right - left, full_h],
            }
        )

    for row in range(1, rows):
        y = row * chunk_h
        top = max(0, y - half)
        bottom = min(full_h, y + half)
        patches.append(
            {
                "patch_id": f"horizontal_row_{row - 1}_{row}",
                "kind": "horizontal",
                "rect": [0, top, full_w, bottom - top],
            }
        )

    for col in range(1, cols):
        for row in range(1, rows):
            x = col * chunk_w
            y = row * chunk_h
            left = max(0, x - half)
            top = max(0, y - half)
            right = min(full_w, x + half)
            bottom = min(full_h, y + half)
            patches.append(
                {
                    "patch_id": f"intersection_{col - 1}_{col}_row_{row - 1}_{row}",
                    "kind": "intersection",
                    "rect": [left, top, right - left, bottom - top],
                }
            )

    return patches


def make_seam_contexts(
    manifest_path,
    output_dir,
    *,
    patch_size=1536,
    max_context_width=1800,
    targets=None,
    only_targets=False,
):
    manifest_path, manifest = load_manifest(manifest_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    assembled = build_assembled_image(manifest)
    save_preview_image(
        assembled,
        output_dir / "assembled_before.png",
        manifest,
        max_width=max_context_width,
        draw_grid=True,
        draw_labels=True,
    )
    patch_specs = [] if only_targets else _build_patch_specs(manifest, int(patch_size))
    for target in targets or []:
        patch_specs.append(_parse_target_spec(target, manifest, int(patch_size)))

    patches = [
        _write_patch(output_dir, patch, assembled, manifest, max_context_width)
        for patch in patch_specs
    ]

    summary = {
        "manifest": str(manifest_path),
        "output_dir": str(output_dir),
        "patch_size": int(patch_size),
        "patch_count": len(patches),
        "patches": patches,
    }
    (output_dir / "metadata.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def make_patch_from_issue(manifest_path, pass_dir, issue: dict, *, max_context_width=1800):
    manifest_path, manifest = load_manifest(manifest_path)
    pass_dir = Path(pass_dir)
    assembled = build_assembled_image(manifest)
    patch = _patch_from_issue(issue, manifest)
    return _write_patch(pass_dir, patch, assembled, manifest, max_context_width)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Create seam repair contexts from painted chunks.")
    parser.add_argument("--manifest", required=True, help="Path to chunks_manifest.json.")
    parser.add_argument("--output", required=True, help="Output seam pass folder.")
    parser.add_argument("--patch-size", type=int, default=1536, help="Total seam patch width.")
    parser.add_argument(
        "--max-context-width",
        type=int,
        default=1800,
        help="Max width for context/diagnostic previews.",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help=(
            "Add a targeted semantic patch. Format: "
            "id=name,center=x:y,size=wxh,goal=connect_walkway,"
            "connections=north_to_south;west_to_east,notes=text"
        ),
    )
    parser.add_argument(
        "--only-targets",
        action="store_true",
        help="Generate only --target patches instead of the automatic seam set.",
    )
    args = parser.parse_args(argv)

    result = make_seam_contexts(
        args.manifest,
        args.output,
        patch_size=args.patch_size,
        max_context_width=args.max_context_width,
        targets=args.target,
        only_targets=args.only_targets,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
