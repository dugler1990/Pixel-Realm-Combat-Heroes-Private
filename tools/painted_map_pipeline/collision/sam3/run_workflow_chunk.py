"""Run Roboflow Custom Workflow on one painted chunk."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from ..emit import chunk_entry, load_manifest
from .roboflow_workflow import (
    WorkflowError,
    chunk_output_dir,
    load_config,
    run_workflow,
    write_chunk_outputs,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def run_workflow_chunk(
    *,
    chunk_id: str,
    manifest_path: Path,
    config: dict,
    repo: Path,
    painted_path: Path | None = None,
    probe_only: bool = False,
) -> Path:
    manifest = load_manifest(manifest_path)
    chunk = chunk_entry(manifest, chunk_id)
    if painted_path is None:
        painted_path = Path(chunk["painted_image"])
        if not painted_path.is_absolute():
            painted_path = (repo / painted_path).resolve()
    if not painted_path.exists():
        raise FileNotFoundError(f"Missing painted chunk: {painted_path}")

    with Image.open(painted_path) as im:
        image_size = im.size

    output_dir = chunk_output_dir(config, repo, chunk_id)
    print(f"Running workflow for {chunk_id} …", flush=True)
    result = run_workflow(painted_path, config)
    print(f"  parsing response for {chunk_id} …", flush=True)
    return write_chunk_outputs(
        output_dir=output_dir,
        chunk_id=chunk_id,
        painted_image=painted_path,
        image_size=image_size,
        result=result,
        probe_only=probe_only,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Roboflow workflow obstacle polygons for one painted chunk.")
    parser.add_argument("--chunk", default="chunk_06_06")
    parser.add_argument(
        "--manifest",
        default="levels/Frostreach/expanse/export/painted_4k_leonardo/insert_manifest.json",
    )
    parser.add_argument(
        "--config",
        default="tools/painted_map_pipeline/collision/sam3/sam3.config.example.json",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Save workflow_response.json + summary only (no polygons.json yet).",
    )
    args = parser.parse_args(argv)

    repo = _repo_root()
    config = load_config((repo / args.config).resolve())
    try:
        output_dir = run_workflow_chunk(
            chunk_id=args.chunk,
            manifest_path=(repo / args.manifest).resolve(),
            config=config,
            repo=repo,
            probe_only=args.probe,
        )
    except WorkflowError as exc:
        print(f"Workflow failed: {exc}")
        return 1

    print(f"Workflow output -> {output_dir}")
    print(f"  response: {output_dir / 'workflow_response.json'}")
    print(f"  summary:  {output_dir / 'workflow_response_summary.txt'}")
    if not args.probe:
        print(f"  polygons: {output_dir / 'polygons.json'}")
        print(f"  preview:  {output_dir / 'overlay_preview.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
