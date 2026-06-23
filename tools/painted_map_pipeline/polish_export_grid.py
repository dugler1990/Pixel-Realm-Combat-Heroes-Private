"""Polish exported PaintedGround grid chunks via Leonardo.Ai."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image

from .image_client import ImageClientError, make_image_client
from .prompt_builder import DEFAULT_STYLE_PROMPT


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
) -> dict:
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if dry_run:
        image_config = dict(image_config)
        image_config["provider"] = "manifest"

    preserve_existing = bool(image_config.get("preserve_existing", False))
    results = []

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

        per_chunk_config = dict(image_config)
        if not image_config.get("preserve_native_resolution", True):
            per_chunk_config["target_output_size"] = [int(out_w), int(out_h)]
        client = make_image_client(per_chunk_config)

        chunk_prompt_base = edge_prompt if chunk.get("padded") and edge_prompt else prompt
        chunk_prompt = "\n".join(
            [
                chunk_prompt_base,
                "",
                f"Chunk ID: {chunk_id}",
                f"Target output size: {out_w}x{out_h}",
                "Preserve the input layout exactly while improving painted terrain detail.",
            ]
        )

        try:
            result = client.generate(chunk_prompt, [str(source_path)], str(output_path))
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

        result["chunk_id"] = chunk_id
        result["source_path"] = str(source_path)
        result["output_pixel_rect"] = [0, 0, int(out_w), int(out_h)]
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
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
