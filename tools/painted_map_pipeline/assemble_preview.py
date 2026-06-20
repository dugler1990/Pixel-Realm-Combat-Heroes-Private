from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None


def _resample_filter():
    resampling = getattr(Image, "Resampling", Image)
    return getattr(resampling, "LANCZOS", Image.BICUBIC)


def _chunk_rect(chunk: dict):
    return [int(v) for v in chunk.get("source_rect_with_overlap", chunk["world_rect"])]


def load_manifest(manifest_path):
    manifest_path = Path(manifest_path)
    return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8"))


def build_assembled_image(manifest: dict, *, scale=1.0):
    full_w, full_h = [int(v) for v in manifest["image_size"]]
    canvas = Image.new(
        "RGBA",
        (max(1, int(round(full_w * scale))), max(1, int(round(full_h * scale)))),
        (0, 0, 0, 255),
    )

    for chunk in manifest.get("chunks", []):
        image_path = Path(chunk["painted_image"])
        if not image_path.exists():
            continue
        x, y, w, h = _chunk_rect(chunk)
        with Image.open(image_path) as image:
            image = image.convert("RGBA")
            target_size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
            if image.size != target_size:
                image = image.resize(target_size, _resample_filter())
            canvas.alpha_composite(image, (int(round(x * scale)), int(round(y * scale))))
    return canvas


def save_preview_image(
    image: Image.Image,
    output_path,
    manifest: dict,
    *,
    max_width=None,
    draw_grid=False,
    draw_labels=False,
    coord_scale=1.0,
):
    if max_width and image.width > max_width:
        resize_scale = int(max_width) / image.width
        canvas = image.resize(
            (int(max_width), max(1, int(round(image.height * resize_scale)))),
            _resample_filter(),
        )
        draw_scale = coord_scale * resize_scale
    else:
        canvas = image.copy()
        draw_scale = coord_scale
    if draw_grid or draw_labels:
        draw = ImageDraw.Draw(canvas)
        for chunk in manifest.get("chunks", []):
            x, y, w, h = _chunk_rect(chunk)
            left = int(round(x * draw_scale))
            top = int(round(y * draw_scale))
            right = int(round((x + w) * draw_scale)) - 1
            bottom = int(round((y + h) * draw_scale)) - 1
            if draw_grid:
                draw.rectangle((left, top, right, bottom), outline=(255, 0, 0, 255), width=2)
            if draw_labels:
                draw.text((left + 8, top + 8), chunk["chunk_id"], fill=(255, 0, 0, 255))

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    return {"output_path": str(output_path), "size": list(canvas.size)}


def assemble_preview(
    manifest_path,
    output_path=None,
    *,
    max_width=None,
    draw_grid=False,
    draw_labels=False,
):
    manifest_path, manifest = load_manifest(manifest_path)
    scale = 1.0
    if max_width:
        full_w = int(manifest["image_size"][0])
        if full_w > int(max_width):
            scale = int(max_width) / full_w
    canvas = build_assembled_image(manifest, scale=scale)
    if output_path is None:
        output_path = manifest_path.parent.parent / "assembled_preview.png"
    return save_preview_image(
        canvas,
        output_path,
        manifest,
        draw_grid=draw_grid,
        draw_labels=draw_labels,
        coord_scale=scale,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Assemble painted chunk images into one preview.")
    parser.add_argument("--manifest", required=True, help="Path to chunks_manifest.json.")
    parser.add_argument("--output", help="Output preview PNG path.")
    parser.add_argument("--max-width", type=int, help="Optional preview max width.")
    parser.add_argument("--grid", action="store_true", help="Draw chunk borders.")
    parser.add_argument("--labels", action="store_true", help="Draw chunk ids.")
    args = parser.parse_args(argv)

    result = assemble_preview(
        args.manifest,
        args.output,
        max_width=args.max_width,
        draw_grid=args.grid,
        draw_labels=args.labels,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
