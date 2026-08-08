"""Conform a raw model output onto the silhouette.

The v1 bug lived here: it *always* RBF-warped, so a full-frame output got the
rectangle-outline mapped onto the irregular silhouette → melt. v2 chooses a
strategy from the backend's declared capability and the measured fit, and defaults
to a hard crop. Warp (v1 land_fit) is demoted to an opt-in strategy for near-fits,
ported in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import imaging
from .config import ConformConfig


@dataclass(frozen=True)
class FitMetrics:
    content_area_ratio: float  # raw content area / silhouette area
    iou: float                 # IoU(raw content, silhouette)


@dataclass(frozen=True)
class ConformReport:
    strategy: str
    fit: FitMetrics
    notes: tuple[str, ...]
    output_path: str


def measure_fit(raw: np.ndarray, silhouette: np.ndarray) -> FitMetrics:
    content = imaging.content_bool(raw)
    return FitMetrics(
        content_area_ratio=imaging.area_ratio(content, silhouette),
        iou=imaging.iou(content, silhouette),
    )


def choose_strategy(enforces_region: bool, fit: FitMetrics, cfg: ConformConfig) -> str:
    if cfg.strategy != "auto":
        return cfg.strategy
    if enforces_region:
        return "identity"  # backend already froze the outside; trust it
    if fit.content_area_ratio > cfg.overflow_area_ratio:
        return "crop"      # full-frame output => hard crop, never warp
    if fit.iou >= cfg.warp_min_iou:
        return "identity"  # already lines up; masking is enough
    return "warp"          # near-fit misalignment => warp (Phase 2)


def conform(
    *,
    raw_path: str | Path,
    silhouette_mask_path: str | Path,
    out_path: str | Path,
    outside_color: tuple[int, int, int, int],
    enforces_region: bool,
    cfg: ConformConfig,
    locked_pixels_path: str | Path | None = None,
    locked_mask_path: str | Path | None = None,
) -> ConformReport:
    raw = imaging.load_rgba(raw_path)
    silhouette = imaging.load_mask_bool(silhouette_mask_path)
    if raw.shape[:2] != silhouette.shape[:2]:
        raise ValueError(
            f"raw {raw.shape[1]}x{raw.shape[0]} != silhouette {silhouette.shape[1]}x{silhouette.shape[0]}"
        )

    fit = measure_fit(raw, silhouette)
    strategy = choose_strategy(enforces_region, fit, cfg)
    notes: list[str] = []

    if strategy == "warp":
        # Phase 2 will port land_fit here. Until then, degrade safely to crop
        # rather than melt — the whole point of this rewrite.
        notes.append("warp requested but not implemented (Phase 2); using crop")
        strategy_effective = "crop"
    else:
        strategy_effective = strategy

    # identity and crop are the same non-warping operation: hard-mask to silhouette.
    result = imaging.mask_to_silhouette(raw, silhouette, outside_color)

    # Paste the locked pad back so neighbor continuity is exact (freeze region).
    if locked_pixels_path and locked_mask_path:
        locked = imaging.load_rgba(locked_pixels_path)
        locked_mask = imaging.load_mask_bool(locked_mask_path)
        if np.any(locked_mask):
            result[locked_mask] = locked[locked_mask]
            notes.append("pasted locked pad")

    imaging.save_rgba(result, out_path)
    return ConformReport(
        strategy=strategy_effective,
        fit=fit,
        notes=tuple(notes),
        output_path=str(out_path),
    )
