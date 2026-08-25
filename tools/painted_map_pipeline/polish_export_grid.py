"""Polish exported PaintedGround grid chunks via Leonardo.Ai."""

from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .image_client import ImageClientError, make_image_client
from .openai_api import EDGE_MULTIPLE, MAX_ASPECT, MIN_PIXELS
from .prompt_builder import DEFAULT_STYLE_PROMPT

Image.MAX_IMAGE_PIXELS = None


def _outside_mask(source_path: Path) -> np.ndarray:
    """Boolean mask of pixels OUTSIDE the playable art: near-black regions connected to the
    image border. Interior dark pixels (shadows, dark stone) stay untouched because they do
    not touch the border. All-False for full-bleed chunks (no black edge)."""
    src = np.asarray(Image.open(source_path).convert("RGB")).astype(int)
    black = (src.sum(axis=2) <= 40).astype(np.uint8)
    if not black.any():
        return np.zeros(black.shape, dtype=bool)
    _, labels = cv2.connectedComponents(black, connectivity=4)
    border_labels = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border_labels.discard(0)  # 0 = the non-black area
    if not border_labels:
        return np.zeros(black.shape, dtype=bool)
    return np.isin(labels, list(border_labels))


def _legal_land_box(outside: np.ndarray, margin: int = 64) -> tuple[int, int, int, int]:
    """Smallest legal generation box (16-multiple edges, >= MIN_PIXELS, aspect <= MAX_ASPECT)
    covering the chunk's land, centred on it and clamped inside the chunk. Lets a chunk whose
    land is a small sliver be generated as a small, cheap image instead of a full-size one."""
    chunk_h, chunk_w = outside.shape
    ys, xs = np.where(~outside)
    left, top = int(xs.min()), int(ys.min())
    right, bottom = int(xs.max()) + 1, int(ys.max()) + 1
    left, top = max(0, left - margin), max(0, top - margin)
    right, bottom = min(chunk_w, right + margin), min(chunk_h, bottom + margin)
    w, h = right - left, bottom - top
    if w > h * MAX_ASPECT:
        h = int(math.ceil(w / MAX_ASPECT))
    elif h > w * MAX_ASPECT:
        w = int(math.ceil(h / MAX_ASPECT))
    if w * h < MIN_PIXELS:
        scale = (MIN_PIXELS / (w * h)) ** 0.5
        w, h = int(math.ceil(w * scale)), int(math.ceil(h * scale))
    snap = EDGE_MULTIPLE
    w = min(chunk_w - chunk_w % snap, ((w + snap - 1) // snap) * snap)
    h = min(chunk_h - chunk_h % snap, ((h + snap - 1) // snap) * snap)
    while w * h < MIN_PIXELS:  # clamped against a chunk edge: grow the other side
        if h < chunk_h - chunk_h % snap:
            h += snap
        elif w < chunk_w - chunk_w % snap:
            w += snap
        else:
            break
    cx, cy = (left + right) // 2, (top + bottom) // 2
    x0 = max(0, min(chunk_w - w, cx - w // 2))
    y0 = max(0, min(chunk_h - h, cy - h // 2))
    return x0, y0, w, h


def _write_locator(base: Image.Image, scale: float, rect: list, dest: Path) -> None:
    """The full map, downscaled, with this chunk's rectangle outlined in magenta."""
    art = base.copy()
    draw = ImageDraw.Draw(art)
    x, y, w, h = [float(v) for v in rect]
    box = [x * scale, y * scale, (x + w) * scale, (y + h) * scale]
    draw.rectangle(box, outline=(255, 0, 255), width=5)
    art.save(dest)


def _enforce_outside_black(source_path: Path, output_path: Path) -> None:
    """Force the generated chunk to pure black wherever the SOURCE was outside the playable
    art. The edge prompt asks the model to leave black alone, but it cannot be trusted (it
    happily invents terrain there), so the boundary is enforced in code -- same principle as
    the world_levels mask compositing."""
    outside = _outside_mask(source_path)
    if not outside.any():
        return
    out = np.asarray(Image.open(output_path).convert("RGB")).copy()
    if out.shape[:2] != outside.shape:
        # Provider returned its own resolution (e.g. Leonardo native size): scale the mask to
        # the output rather than resampling the art.
        outside = cv2.resize(
            outside.astype(np.uint8), (out.shape[1], out.shape[0]), interpolation=cv2.INTER_NEAREST
        ).astype(bool)
    out[outside] = 0
    Image.fromarray(out).save(output_path)


def _load_prompt(prompt_file: Path | None, inline_prompt: str | None) -> str:
    if inline_prompt:
        return inline_prompt.strip()
    if prompt_file and prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8").strip()
    return DEFAULT_STYLE_PROMPT


def _chunks_from_manifest(input_dir: Path) -> list[dict]:
    manifest_path = input_dir / "grid_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return list(manifest.get("chunks", []))
    chunks = []
    for path in sorted(input_dir.glob("chunk_*.png")):
        chunk_id = path.stem
        with Image.open(path) as image:
            w, h = image.size
        chunks.append(
            {
                "chunk_id": chunk_id,
                "file": str(path),
                "output_pixel_rect": [0, 0, w, h],
            }
        )
    return chunks


def polish_export_grid(
    input_dir: Path,
    output_dir: Path,
    *,
    prompt: str,
    edge_prompt: str | None = None,
    image_config: dict,
    chunk_ids: set[str] | None = None,
    dry_run: bool = False,
    use_locator: bool = True,
) -> dict:
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        image_config = dict(image_config)
        image_config["provider"] = "manifest"

    preserve_existing = bool(image_config.get("preserve_existing", False))
    results = []

    # Orientation locator: the full map, downscaled once; each chunk gets a copy with its own
    # rectangle outlined, passed as image 2 so the model knows what partial shapes belong to.
    # Only providers that accept multiple input images get it.
    locator_base = None
    locator_scale = 1.0
    provider = str(image_config.get("provider") or "").strip().lower()
    manifest_path = input_dir / "grid_manifest.json"
    # grid position -> chunk, for neighbour lookup
    by_grid: dict[tuple[int, int], dict] = {}
    for entry in _chunks_from_manifest(input_dir):
        if entry.get("grid"):
            by_grid[(int(entry["grid"][0]), int(entry["grid"][1]))] = entry
    if use_locator and provider in {"openai", "manifest", "dry_run", "dry-run"} and manifest_path.exists():
        meta = json.loads(manifest_path.read_text(encoding="utf-8"))
        source_image = meta.get("source_image")
        if source_image and Path(source_image).exists():
            with Image.open(source_image) as full:
                fw, fh = full.size
                locator_scale = min(1536.0 / fw, 1536.0 / fh, 1.0)
                locator_base = full.convert("RGB").resize(
                    (max(1, int(fw * locator_scale)), max(1, int(fh * locator_scale)))
                )

    for chunk in _chunks_from_manifest(input_dir):
        chunk_id = chunk.get("chunk_id") or Path(chunk["file"]).stem
        if chunk_ids and chunk_id not in chunk_ids:
            continue

        source_path = Path(chunk.get("file") or (input_dir / f"{chunk_id}.png"))
        if not source_path.exists():
            raise ImageClientError(f"Missing chunk source: {source_path}")

        _, _, out_w, out_h = chunk.get("output_pixel_rect", [0, 0, 0, 0])
        if not out_w or not out_h:
            with Image.open(source_path) as image:
                out_w, out_h = image.size

        output_path = output_dir / f"{chunk_id}.png"
        context_dir = output_dir / chunk_id / "context"
        context_dir.mkdir(parents=True, exist_ok=True)

        if preserve_existing and output_path.exists():
            result = {
                "provider": "preserve_existing",
                "chunk_id": chunk_id,
                "output_path": str(output_path),
                "preserved": True,
            }
            results.append(result)
            (context_dir / "image_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            continue

        # A chunk that is (almost) entirely outside the playable art has nothing to paint:
        # spend no API call, keep it black.
        outside = _outside_mask(source_path)
        if outside.mean() > 0.999:
            shutil.copy2(source_path, output_path)
            result = {
                "provider": "skipped_empty",
                "chunk_id": chunk_id,
                "output_path": str(output_path),
                "skipped_empty": True,
            }
            results.append(result)
            (context_dir / "image_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            continue

        per_chunk_config = dict(image_config)
        if not image_config.get("preserve_native_resolution", True):
            per_chunk_config["target_output_size"] = [int(out_w), int(out_h)]
        client = make_image_client(per_chunk_config)

        # A chunk whose land is a small sliver becomes a small, cheap generation: crop to the
        # smallest legal box covering the land, generate that, paste back onto black. No
        # skipped/unpainted class -- every land chunk gets painted, cost scales with land.
        # gpt-only: its cost scales with pixels and it returns exact sizes; other providers
        # (Leonardo) bill per generation and return their own resolution, so cropping there
        # saves nothing and the paste-back could not assume sizes.
        chunk_h_px, chunk_w_px = outside.shape
        mini_box = None
        if provider in {"openai", "manifest", "dry_run", "dry-run"}:
            box = _legal_land_box(outside)
            if box[2] * box[3] <= 0.6 * chunk_w_px * chunk_h_px:
                mini_box = box

        gen_source, gen_output = source_path, output_path
        if mini_box:
            x0, y0, mw, mh = mini_box
            gen_source = context_dir / "mini_source.png"
            gen_output = context_dir / "mini_generated.png"
            with Image.open(source_path) as src_img:
                src_img.convert("RGB").crop((x0, y0, x0 + mw, y0 + mh)).save(gen_source)

        locator_path = None
        if locator_base is not None and chunk.get("source_pixel_rect"):
            locator_path = context_dir / "locator.png"
            _write_locator(locator_base, locator_scale, chunk["source_pixel_rect"], locator_path)

        # Neighbour context: the adjacent chunks, preferring ones already painted in this run,
        # so each chunk is drawn against what it actually sits next to instead of blind. This is
        # the continuity mechanism prompt_builder built packs for; here they are sent to the model.
        neighbours: list[tuple[str, Path]] = []
        if by_grid and chunk.get("grid"):
            col, row = (int(v) for v in chunk["grid"])
            for direction, (dc, dr) in (("west", (-1, 0)), ("east", (1, 0)),
                                        ("north", (0, -1)), ("south", (0, 1))):
                other = by_grid.get((col+dc, row+dr))
                if not other:
                    continue
                other_id = other.get("chunk_id") or ""
                painted = output_dir / f"{other_id}.png"
                raw = Path(other.get("file") or (input_dir / f"{other_id}.png"))
                path = painted if painted.exists() else raw
                if path.exists():
                    neighbours.append((direction, path))

        # Prompt and image roster are built together: position in the list is the only label
        # the model gets, so the text must reference images by that position.
        chunk_prompt_base = edge_prompt if chunk.get("padded") and edge_prompt else prompt
        lines = [chunk_prompt_base]
        if locator_path is not None:
            lines += [
                "",
                "Image 1 is the map chunk to redraw. Image 2 is the FULL map with this chunk's "
                "location outlined in magenta, for orientation only: use it to understand what "
                "the partial shapes in image 1 belong to (a corner of a large structure, part "
                "of a larger formation, and so on). Do not copy content, framing, or scale from "
                "image 2. Redraw image 1 only, keeping its layout exactly.",
            ]
        if neighbours:
            first = 3 if locator_path else 2
            listing = ", ".join(
                f"image {first+i} = the {d} neighbour" for i, (d, _) in enumerate(neighbours)
            )
            lines += [
                "",
                f"The remaining images are the adjoining map chunks ({listing}). Use them ONLY for "
                "continuity across the shared edge: match their colour, tone, brightness and "
                "texture density so the chunks read as one continuous painting, and carry any "
                "feature that crosses the border straight through. Do NOT copy a neighbour's "
                "composition or content into this chunk -- image 1's layout is what you redraw.",
            ]
        lines += [
            "",
            f"Chunk ID: {chunk_id}",
            "Preserve the input layout exactly while improving painted terrain detail.",
        ]
        chunk_prompt = "\n".join(lines)

        input_images = [str(gen_source)] + ([str(locator_path)] if locator_path else [])
        input_images += [str(p) for _, p in neighbours]
        try:
            result = client.generate(chunk_prompt, input_images, str(gen_output))
        except ImageClientError as exc:
            result = {
                "provider": per_chunk_config.get("provider", "leonardo"),
                "chunk_id": chunk_id,
                "error": str(exc),
                "source_path": str(source_path),
            }
            results.append(result)
            (context_dir / "image_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            continue

        if not dry_run:
            if mini_box:
                x0, y0, mw, mh = mini_box
                canvas = Image.new("RGB", (chunk_w_px, chunk_h_px), (0, 0, 0))
                with Image.open(gen_output) as mini_img:
                    canvas.paste(mini_img.convert("RGB"), (x0, y0))
                canvas.save(output_path)
            _enforce_outside_black(source_path, output_path)
        result["chunk_id"] = chunk_id
        result["source_path"] = str(source_path)
        result["output_pixel_rect"] = [0, 0, int(out_w), int(out_h)]
        if mini_box:
            result["mini_rect"] = list(mini_box)
        if locator_path is not None:
            result["locator"] = str(locator_path)
        results.append(result)
        (context_dir / "image_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        shutil.copy2(source_path, context_dir / "source.png")

    summary = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "dry_run": dry_run,
        "image_config": {k: v for k, v in image_config.items() if k != "api_key"},
        "results": results,
    }
    (output_dir / "leonardo_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _load_config(config_path: Path | None) -> dict:
    if not config_path:
        return {}
    return json.loads(config_path.read_text(encoding="utf-8"))


def _resolve_user_path(raw: str, *, must_exist: bool = False) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    base = Path(__file__).resolve().parent
    repo_root = base.parents[1]
    if not must_exist:
        return (repo_root / path).resolve()
    for root in (Path.cwd(), repo_root):
        candidate = (root / path).resolve()
        if candidate.exists():
            return candidate
    return (repo_root / path).resolve()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Polish exported grid PNGs with Leonardo.Ai.")
    parser.add_argument(
        "--input-dir",
        default="levels/Frostreach/expanse/export/painted_4k",
        help="Folder with chunk_*.png and optional grid_manifest.json",
    )
    parser.add_argument(
        "--output-dir",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo",
        help="Output folder for polished chunks",
    )
    parser.add_argument(
        "--config",
        default="tools/painted_map_pipeline/leonardo.config.example.json",
        help="Leonardo config JSON",
    )
    parser.add_argument("--prompt-file", default="tools/painted_map_pipeline/frostreach_polish_prompt.txt")
    parser.add_argument(
        "--edge-prompt-file",
        default="tools/painted_map_pipeline/frostreach_edge_polish_prompt.txt",
        help="Prompt for padded edge chunks (uses --prompt-file for interior cells).",
    )
    parser.add_argument("--prompt", default=None, help="Inline prompt override")
    parser.add_argument("--chunk-id", action="append", default=[], help="Process only these chunk ids")
    parser.add_argument("--dry-run", action="store_true", help="Write manifest requests without calling Leonardo")
    parser.add_argument("--preserve-existing", action="store_true")
    parser.add_argument(
        "--no-locator",
        action="store_true",
        help="Do not attach the full-map orientation locator as a second input image.",
    )
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parent
    image_config = _load_config(_resolve_user_path(args.config, must_exist=True))
    image_config.setdefault("provider", "leonardo")
    if args.preserve_existing:
        image_config["preserve_existing"] = True

    prompt = _load_prompt(_resolve_user_path(args.prompt_file, must_exist=True), args.prompt)
    edge_prompt_path = _resolve_user_path(args.edge_prompt_file, must_exist=False)
    edge_prompt = _load_prompt(edge_prompt_path, None) if edge_prompt_path.exists() else None
    summary = polish_export_grid(
        _resolve_user_path(args.input_dir, must_exist=True),
        _resolve_user_path(args.output_dir),
        prompt=prompt,
        edge_prompt=edge_prompt,
        image_config=image_config,
        chunk_ids=set(args.chunk_id or []),
        dry_run=args.dry_run,
        use_locator=not args.no_locator,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
