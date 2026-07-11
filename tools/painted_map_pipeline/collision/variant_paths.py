"""Shared collision trial output paths ({output_root}/{chunk_id}/{variant}/)."""

from __future__ import annotations

from pathlib import Path

DEFAULT_LEONARDO_VARIANT = "leonardo_direct"


def chunk_variant_dir(output_root: Path, chunk_id: str, variant: str) -> Path:
    return Path(output_root) / chunk_id / variant


def variant_batch_summary_path(output_root: Path, variant: str) -> Path:
    return Path(output_root) / f"{variant}_batch_summary.json"
