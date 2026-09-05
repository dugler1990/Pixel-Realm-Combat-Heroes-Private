"""Generate one chunk heightmap via ImageClient, then align and QC."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..collision.emit import chunk_entry, load_manifest
from ..image_client import ImageClientError, make_image_client, output_matches_source_size
from .align import HeightmapQCError, QC_MAX_SHIFT_PX, QC_MIN_RESPONSE, align_generated


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def source_path_for_chunk(chunk: dict[str, Any], repo: Path) -> Path:
    painted = Path(chunk["painted_image"])
    if not painted.is_absolute():
        painted = (repo / painted).resolve()
    sibling = painted.parent / "source.png"
    if sibling.is_file():
        return sibling
    return painted


def chunk_output_dir(chunk: dict[str, Any], repo: Path, attempt: int | None) -> Path:
    source = source_path_for_chunk(chunk, repo)
    base = source.parent
    if attempt is None:
        return base
    return base / "heightmap_attempts" / f"{int(attempt):02d}"


def heightmap_paths(out_dir: Path) -> dict[str, Path]:
    return {
        "raw": out_dir / "heightmap_raw.png",
        "height": out_dir / "heightmap.png",
        "preview": out_dir / "heightmap_preview.png",
        "result": out_dir / "heightmap_result.json",
    }


def should_preserve(height_path: Path, source_path: Path, preserve_existing: bool) -> bool:
    return bool(preserve_existing and output_matches_source_size(height_path, source_path))


def run_heightmap_chunk(
    *,
    chunk_id: str,
    manifest_path: Path,
    config: dict[str, Any],
    repo: Path,
    preserve_existing: bool | None = None,
    attempt: int | None = None,
    promote: bool = False,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    chunk = chunk_entry(manifest, chunk_id)
    source_path = source_path_for_chunk(chunk, repo)
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing source for {chunk_id}: {source_path}")

    preserve = (
        bool(config.get("preserve_existing", True))
        if preserve_existing is None
        else bool(preserve_existing)
    )
    out_dir = chunk_output_dir(chunk, repo, attempt)
    paths = heightmap_paths(out_dir)
    canonical = heightmap_paths(source_path.parent)

    if attempt is None and should_preserve(canonical["height"], source_path, preserve):
        result = {
            "chunk_id": chunk_id,
            "provider": "preserve_existing",
            "preserved": True,
            "output_path": str(canonical["height"]),
        }
        if canonical["result"].exists():
            try:
                prior = json.loads(canonical["result"].read_text(encoding="utf-8"))
                prior.update(result)
                result = prior
            except json.JSONDecodeError:
                pass
        canonical["result"].write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result

    prompt = str(config.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("heightmap config has no prompt")

    client = make_image_client(config)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        api_result = client.generate(prompt, [str(source_path)], str(paths["raw"]))
    except ImageClientError as exc:
        raise ImageClientError(f"{chunk_id}: {exc}") from exc

    max_shift = int(config.get("qc_max_shift_px", QC_MAX_SHIFT_PX))
    min_response = float(config.get("qc_min_response", QC_MIN_RESPONSE))
    qc = align_generated(
        paths["raw"],
        source_path,
        height_out=paths["height"],
        preview_out=paths["preview"],
        max_shift_px=max_shift,
        min_response=min_response,
    )

    result: dict[str, Any] = {
        "chunk_id": chunk_id,
        "source": str(source_path),
        "raw": str(paths["raw"]),
        "output_path": str(paths["height"]),
        "attempt": attempt,
        "qc": qc,
        "api": api_result,
    }
    paths["result"].write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    if promote and attempt is not None and qc.get("ok"):
        import shutil

        for key in ("height", "preview", "raw", "result"):
            shutil.copy2(paths[key], canonical[key])

    if not qc.get("ok"):
        raise HeightmapQCError(
            f"{chunk_id}: registration QC failed: {qc.get('reason')} "
            f"dx={qc.get('dx')} dy={qc.get('dy')} response={qc.get('response')}"
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ImageClient heightmap for one painted chunk.")
    parser.add_argument("--chunk", default="chunk_00_02")
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/sunspine_7x6_play/export/sam3_chunks/insert_manifest.json",
    )
    parser.add_argument(
        "--config",
        default="tools/painted_map_pipeline/heightmap.sunspine.json",
    )
    parser.add_argument("--preserve-existing", action="store_true", default=None)
    parser.add_argument("--no-preserve-existing", action="store_false", dest="preserve_existing")
    parser.add_argument("--attempt", type=int, default=None, help="Write under heightmap_attempts/NN/")
    parser.add_argument(
        "--promote",
        action="store_true",
        help="If --attempt QC passes, copy outputs onto the chunk heightmap.png",
    )
    args = parser.parse_args(argv)

    repo = _repo_root()
    config = load_config((repo / args.config).resolve())
    try:
        result = run_heightmap_chunk(
            chunk_id=args.chunk,
            manifest_path=(repo / args.manifest).resolve(),
            config=config,
            repo=repo,
            preserve_existing=args.preserve_existing,
            attempt=args.attempt,
            promote=args.promote,
        )
    except (HeightmapQCError, ImageClientError, FileNotFoundError, KeyError, ValueError) as exc:
        print(f"FAIL {args.chunk}: {exc}")
        return 1
    if result.get("preserved"):
        print(f"KEEP {args.chunk} -> {result.get('output_path')}")
        return 0
    qc = result.get("qc") or {}
    print(
        f"DONE {args.chunk} dx={qc.get('dx')} dy={qc.get('dy')} "
        f"response={qc.get('response')} -> {result.get('output_path')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
