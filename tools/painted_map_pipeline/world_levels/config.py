from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import CanvasConfig, ExecutionConfig, RunConfig, SplitConfig


def _path(value: Any, base_dir: Path, field: str, *, required: bool = True) -> Path | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"{field} is required")
        return None
    path = Path(str(value)).expanduser()
    return (base_dir / path).resolve() if not path.is_absolute() else path.resolve()


def _positive_int(value: Any, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _parse_split(raw: Any) -> SplitConfig | None:
    """Parse the optional `split` block. Returns None when absent so existing configs
    (with no split block) serialize and hash exactly as before."""
    if not raw:
        return None
    if not isinstance(raw, dict):
        raise ValueError("split must be an object")
    defaults = SplitConfig()

    buckets_raw = raw.get("buckets")
    if buckets_raw is None:
        buckets = defaults.buckets
    else:
        if not isinstance(buckets_raw, list) or not buckets_raw:
            raise ValueError("split.buckets must be a non-empty list of [area, count]")
        buckets_list: list[tuple[float, int]] = []
        last_upper = 0.0
        for entry in buckets_raw:
            if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                raise ValueError("each split.buckets entry must be [upper_area, count]")
            upper, count = float(entry[0]), int(entry[1])
            if upper <= last_upper:
                raise ValueError("split.buckets upper bounds must be strictly ascending")
            if count <= 0:
                raise ValueError("split.buckets counts must be positive")
            buckets_list.append((upper, count))
            last_upper = upper
        buckets = tuple(buckets_list)

    min_sub = int(raw.get("min_sublevels", defaults.min_sublevels))
    max_sub = int(raw.get("max_sublevels", defaults.max_sublevels))
    if min_sub < 1 or max_sub < min_sub:
        raise ValueError("split requires 1 <= min_sublevels <= max_sublevels")
    overlap_buffer = int(raw.get("overlap_buffer_px", defaults.overlap_buffer_px))
    crop_margin = int(raw.get("crop_margin_px", defaults.crop_margin_px))
    if overlap_buffer < 0 or crop_margin < 0:
        raise ValueError("split overlap_buffer_px and crop_margin_px must be non-negative")

    return SplitConfig(
        buckets=buckets,
        default_count=int(raw.get("default_count", defaults.default_count)),
        min_sublevels=min_sub,
        max_sublevels=max_sub,
        overlap_buffer_px=overlap_buffer,
        crop_margin_px=crop_margin,
        smooth_kernel=int(raw.get("smooth_kernel", defaults.smooth_kernel)),
        simplify_tolerance=float(raw.get("simplify_tolerance", defaults.simplify_tolerance)),
        criteria=str(raw.get("criteria") or defaults.criteria),
        proposer=dict(raw.get("proposer") or {}),
    )


def parse_config(raw: dict[str, Any], config_path: Path) -> RunConfig:
    base_dir = config_path.parent
    canvas_raw = dict(raw.get("canvas") or {})
    canvas_mode = str(canvas_raw.get("mode") or "").strip().lower()
    if canvas_mode not in {"explicit", "derived"}:
        raise ValueError("canvas.mode must be 'explicit' or 'derived'")
    width = _positive_int(canvas_raw.get("width"), "canvas.width", optional=canvas_mode == "derived")
    height = _positive_int(canvas_raw.get("height"), "canvas.height", optional=canvas_mode == "derived")
    placement = str(canvas_raw.get("placement") or "center").strip().lower()
    if placement not in {"center", "top_left"}:
        raise ValueError("canvas.placement must be 'center' or 'top_left'")
    margin = int(canvas_raw.get("margin", 0))
    if margin < 0:
        raise ValueError("canvas.margin must be non-negative")

    scale_raw = (raw.get("scale") or {}).get("pixels_per_world_pixel")
    if scale_raw is None:
        raise ValueError("scale.pixels_per_world_pixel is required")
    try:
        if float(scale_raw) <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("scale.pixels_per_world_pixel must be positive") from exc

    rendering = dict(raw.get("rendering") or {})
    outside = rendering.get("outside_color", [0, 0, 0, 255])
    if not isinstance(outside, list) or len(outside) != 4:
        raise ValueError("rendering.outside_color must contain four RGBA integers")
    outside_color = tuple(int(channel) for channel in outside)
    if any(channel < 0 or channel > 255 for channel in outside_color):
        raise ValueError("rendering.outside_color channels must be between 0 and 255")
    resampling = str(rendering.get("source_resampling") or "lanczos").strip().lower()
    if resampling not in {"nearest", "bilinear", "bicubic", "lanczos"}:
        raise ValueError("rendering.source_resampling is unsupported")

    execution_raw = dict(raw.get("execution") or {})
    approval_mode = str(execution_raw.get("approval_mode") or "manual").strip().lower()
    if approval_mode not in {"manual", "automatic"}:
        raise ValueError("execution.approval_mode must be 'manual' or 'automatic'")
    retry_limit = int(execution_raw.get("retry_limit", 2))
    if retry_limit < 0:
        raise ValueError("execution.retry_limit must be non-negative")
    rescale_below_iou = float(execution_raw.get("rescale_below_iou", 0.0))
    if not 0.0 <= rescale_below_iou <= 1.0:
        raise ValueError("execution.rescale_below_iou must be between 0 and 1")

    generation_raw = dict(raw.get("generation") or {})
    renderer = str(generation_raw.get("renderer") or "warp").strip().lower()
    if renderer not in {"warp", "frame"}:
        raise ValueError("generation.renderer must be 'warp' or 'frame'")
    generation_raw["renderer"] = renderer
    if renderer == "frame" and approval_mode == "automatic":
        # The frame renderer has no footprint gate -- there is no silhouette to score, so a
        # catastrophic draw is cut, kept, and propagated into every neighbour as padding.
        # A human looking at it is the only defence, so automatic approval is refused.
        raise ValueError(
            "generation.renderer 'frame' requires execution.approval_mode 'manual': "
            "it has no automatic reject gate"
        )

    return RunConfig(
        config_path=config_path.resolve(),
        world_map=_path(raw.get("world_map"), base_dir, "world_map"),  # type: ignore[arg-type]
        level_plan=_path(raw.get("level_plan"), base_dir, "level_plan"),  # type: ignore[arg-type]
        review_overlay=_path(raw.get("review_overlay"), base_dir, "review_overlay", required=False),
        output_root=_path(raw.get("output_root"), base_dir, "output_root"),  # type: ignore[arg-type]
        scale=str(scale_raw),
        canvas=CanvasConfig(canvas_mode, width, height, placement, margin),
        outside_color=outside_color,  # type: ignore[arg-type]
        source_resampling=resampling,
        execution=ExecutionConfig(
            approval_mode=approval_mode,
            stop_on_failure=bool(execution_raw.get("stop_on_failure", True)),
            retry_limit=retry_limit,
            rescale_below_iou=rescale_below_iou,
        ),
        generation=generation_raw,
        style_prompt=str(raw.get("style_prompt") or "").strip(),
        split=_parse_split(raw.get("split")),
    )


def load_config(path: str | Path) -> RunConfig:
    config_path = Path(path).expanduser().resolve()
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("world-level config root must be a JSON object")
    config = parse_config(raw, config_path)
    if not config.world_map.is_file():
        raise FileNotFoundError(f"world map does not exist: {config.world_map}")
    if not config.level_plan.is_file():
        raise FileNotFoundError(f"level plan does not exist: {config.level_plan}")
    return config


def config_as_dict(config: RunConfig) -> dict[str, Any]:
    result: dict[str, Any] = {
        "world_map": str(config.world_map),
        "level_plan": str(config.level_plan),
        "review_overlay": str(config.review_overlay) if config.review_overlay else None,
        "output_root": str(config.output_root),
        "canvas": {
            "mode": config.canvas.mode,
            "width": config.canvas.width,
            "height": config.canvas.height,
            "placement": config.canvas.placement,
            "margin": config.canvas.margin,
        },
        "scale": {"pixels_per_world_pixel": config.scale},
        "rendering": {
            "outside_color": list(config.outside_color),
            "source_resampling": config.source_resampling,
        },
        "execution": {
            "approval_mode": config.execution.approval_mode,
            "stop_on_failure": config.execution.stop_on_failure,
            "retry_limit": config.execution.retry_limit,
            "rescale_below_iou": config.execution.rescale_below_iou,
        },
        "generation": config.generation,
        "style_prompt": config.style_prompt,
    }
    # Only serialize `split` when configured, so existing run roots (no split block)
    # keep their exact config hash.
    if config.split is not None:
        result["split"] = {
            "buckets": [[upper, count] for upper, count in config.split.buckets],
            "default_count": config.split.default_count,
            "min_sublevels": config.split.min_sublevels,
            "max_sublevels": config.split.max_sublevels,
            "overlap_buffer_px": config.split.overlap_buffer_px,
            "crop_margin_px": config.split.crop_margin_px,
            "smooth_kernel": config.split.smooth_kernel,
            "simplify_tolerance": config.split.simplify_tolerance,
            "criteria": config.split.criteria,
            "proposer": config.split.proposer,
        }
    return result
