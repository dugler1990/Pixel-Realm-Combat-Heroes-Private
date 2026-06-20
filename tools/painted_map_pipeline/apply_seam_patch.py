from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from .assemble_preview import assemble_preview, load_manifest
from .insert_chunks import insert_painted_chunks

Image.MAX_IMAGE_PIXELS = None


def _resample_filter():
    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS", Image.BICUBIC)


def _copy_once(src: Path, dst: Path, *, overwrite=False):
    if not src.exists():
        return None
    if dst.exists() and not overwrite:
        raise FileExistsError(f"Backup already exists: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return str(dst)


def _pass_dir_for_patch(patch_dir: Path):
    if patch_dir.parent.name == "patches":
        return patch_dir.parent.parent
    return patch_dir


def _load_patch_metadata(patch_dir: Path):
    metadata_path = patch_dir / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Patch metadata not found: {metadata_path}")
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _load_fixed_image(fixed_image: Path, size, *, allow_resize=False):
    with Image.open(fixed_image) as image:
        image = image.convert("RGBA")
        if image.size != tuple(size):
            if not allow_resize:
                raise ValueError(
                    f"Fixed image size {image.size} does not match patch size {tuple(size)}. "
                    "Regenerate the patch at the exact size or pass --allow-resize-fixed."
                )
            image = image.resize(tuple(size), _resample_filter())
        return image


def _chunk_by_id(manifest: dict):
    return {chunk["chunk_id"]: chunk for chunk in manifest.get("chunks", [])}


def _save_comparison(before: Image.Image, fixed: Image.Image, after: Image.Image, patch_dir: Path):
    before_path = patch_dir / "before.png"
    fixed_path = patch_dir / "fixed.png"
    after_path = patch_dir / "after.png"
    comparison_path = patch_dir / "comparison.png"

    before.save(before_path)
    fixed.save(fixed_path)
    after.save(after_path)

    label_h = 44
    panel_w, panel_h = before.size
    comparison = Image.new("RGBA", (panel_w * 3, panel_h + label_h), (20, 20, 20, 255))
    draw = ImageDraw.Draw(comparison)
    panels = [("before", before), ("fixed", fixed), ("after", after)]
    for idx, (label, image) in enumerate(panels):
        x = idx * panel_w
        comparison.alpha_composite(image, (x, label_h))
        draw.text((x + 12, 12), label, fill=(255, 255, 255, 255))
    comparison.save(comparison_path)
    return {
        "before": str(before_path),
        "fixed": str(fixed_path),
        "after": str(after_path),
        "comparison": str(comparison_path),
    }


def apply_seam_patch(
    manifest_path,
    patch_dir,
    fixed_image,
    *,
    tmx=None,
    output_tmx=None,
    overwrite_backup=False,
    allow_resize_fixed=False,
):
    manifest_path, manifest = load_manifest(manifest_path)
    patch_dir = Path(patch_dir)
    pass_dir = _pass_dir_for_patch(patch_dir)
    fixed_image = Path(fixed_image)
    if not fixed_image.exists():
        raise FileNotFoundError(f"Fixed image not found: {fixed_image}")

    patch = _load_patch_metadata(patch_dir)
    patch_id = patch["patch_id"]
    px, py, pw, ph = [int(v) for v in patch["global_rect"]]
    with Image.open(fixed_image) as original_fixed:
        original_fixed_size = original_fixed.size
    fixed = _load_fixed_image(fixed_image, (pw, ph), allow_resize=allow_resize_fixed)
    with Image.open(patch["source"]) as before_image:
        before_image = before_image.convert("RGBA")

    backups_dir = pass_dir / "backups"
    outputs_dir = pass_dir / "outputs"
    chunk_outputs_dir = outputs_dir / "chunks"
    chunk_outputs_dir.mkdir(parents=True, exist_ok=True)

    backup_paths = {}
    if output_tmx:
        output_tmx_path = Path(output_tmx)
        backed_up = _copy_once(
            output_tmx_path,
            backups_dir / "map_before.tmx",
            overwrite=overwrite_backup,
        )
        if backed_up:
            backup_paths["map_before"] = backed_up
        tileset_path = output_tmx_path.parent / "painted_chunks.tsx"
        backed_up = _copy_once(
            tileset_path,
            backups_dir / "painted_chunks_before.tsx",
            overwrite=overwrite_backup,
        )
        if backed_up:
            backup_paths["painted_chunks_before"] = backed_up

    chunks = _chunk_by_id(manifest)
    affected_results = []
    for affected in patch.get("affected_chunks", []):
        chunk_id = affected["chunk_id"]
        chunk = chunks[chunk_id]
        chunk_path = Path(chunk["painted_image"])
        chunk_backup = _copy_once(
            chunk_path,
            backups_dir / "chunks" / f"{chunk_id}_painted_before.png",
            overwrite=overwrite_backup,
        )
        cx, cy, cw, ch = [int(v) for v in affected["chunk_rect"]]
        ox, oy, ow, oh = [int(v) for v in affected["overlap_rect"]]
        with Image.open(chunk_path) as chunk_image:
            chunk_image = chunk_image.convert("RGBA")
            patch_crop = fixed.crop((ox - px, oy - py, ox - px + ow, oy - py + oh))
            chunk_image.alpha_composite(patch_crop, (ox - cx, oy - cy))

            output_chunk = chunk_outputs_dir / f"{chunk_id}_painted_after.png"
            chunk_image.save(output_chunk)
            chunk_image.save(chunk_path)

        affected_results.append(
            {
                "chunk_id": chunk_id,
                "backup": chunk_backup,
                "output": str(output_chunk),
                "promoted_to": str(chunk_path),
                "overlap_rect": affected["overlap_rect"],
            }
        )

    comparison_paths = _save_comparison(before_image, fixed, fixed, patch_dir)

    assembled_after = pass_dir / "assembled_after.png"
    assemble_preview(
        manifest_path,
        assembled_after,
        max_width=1800,
        draw_grid=True,
        draw_labels=True,
    )

    insert_result = None
    map_after = None
    if tmx and output_tmx:
        insert_result = insert_painted_chunks(tmx, manifest_path, output_tmx)
        map_after = outputs_dir / "map_after.tmx"
        _copy_once(Path(output_tmx), map_after, overwrite=True)

    result = {
        "patch_id": patch_id,
        "patch_dir": str(patch_dir),
        "fixed_image": comparison_paths["fixed"],
        "original_fixed_image": str(fixed_image),
        "original_fixed_size": list(original_fixed_size),
        "fixed_image_was_resized": original_fixed_size != (pw, ph),
        "comparison_paths": comparison_paths,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "backup_paths": backup_paths,
        "affected_chunks": affected_results,
        "assembled_after": str(assembled_after),
        "insert": insert_result,
        "map_after": str(map_after) if map_after else None,
    }
    result_path = patch_dir / "apply_result.json"
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Apply a generated seam patch to painted chunks.")
    parser.add_argument("--manifest", required=True, help="Path to chunks_manifest.json.")
    parser.add_argument("--patch-dir", required=True, help="Patch folder containing metadata.json.")
    parser.add_argument("--fixed-image", required=True, help="Generated fixed patch image.")
    parser.add_argument("--tmx", help="Source outline TMX for reinsertion.")
    parser.add_argument("--output-tmx", help="Final map.tmx to rebuild after applying.")
    parser.add_argument(
        "--overwrite-backup",
        action="store_true",
        help="Allow overwriting existing backups for this pass.",
    )
    parser.add_argument(
        "--allow-resize-fixed",
        action="store_true",
        help="Resize a wrong-sized fixed image to the patch size before applying.",
    )
    args = parser.parse_args(argv)

    result = apply_seam_patch(
        args.manifest,
        args.patch_dir,
        args.fixed_image,
        tmx=args.tmx,
        output_tmx=args.output_tmx,
        overwrite_backup=args.overwrite_backup,
        allow_resize_fixed=args.allow_resize_fixed,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
