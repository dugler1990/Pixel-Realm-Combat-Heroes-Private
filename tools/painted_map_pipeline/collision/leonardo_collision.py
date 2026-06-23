"""Leonardo collision segmentation pass (direct or mechanical-hint input)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from ..image_client import ImageClientError, make_image_client
from .derive import DeriveConfig, derive_collision_masks
from .hint_image import mechanical_flat_map, painted_with_mechanical_overlay, side_by_side_hint
from .package import write_collision_package
from .parse_segmentation import (
    SegmentationColors,
    parse_segmentation_image,
    smooth_masks,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_prompt(path: Path | None, default_name: str) -> str:
    if path and path.exists():
        return path.read_text(encoding="utf-8").strip()
    fallback = Path(__file__).parent / default_name
    return fallback.read_text(encoding="utf-8").strip()


def _fit_gen_size(width: int, height: int, max_side: int) -> tuple[int, int]:
    scale = min(max_side / max(width, 1), max_side / max(height, 1), 1.0)
    w = max(64, int(round(width * scale)))
    h = max(64, int(round(height * scale)))
    w -= w % 8
    h -= h % 8
    return max(64, w), max(64, h)


def build_leonardo_input(
    painted: Image.Image,
    *,
    mode: str,
    mechanical_result=None,
    hint_style: str = "overlay",
    hint_alpha: float = 0.55,
) -> tuple[Image.Image, Path | None]:
    """Return (input_image, temp_hint_path_if_any)."""
    if mode == "direct":
        return painted.convert("RGB"), None

    if mechanical_result is None:
        raise ValueError("hint mode requires mechanical_result")

    style = hint_style.lower()
    if style == "side_by_side":
        return side_by_side_hint(painted, mechanical_result), None
    if style == "flat":
        return mechanical_flat_map(mechanical_result), None
    return painted_with_mechanical_overlay(painted, mechanical_result, alpha=hint_alpha), None


def _parse_masks_from_segmentation(
    segmented: Image.Image,
    full_size: tuple[int, int],
    leonardo_config: dict,
) -> dict:
    if segmented.size != full_size:
        raise ImageClientError(
            f"Leonardo segmentation size {segmented.size} != chunk size {full_size}; "
            "refusing to stretch — re-run with preserve_native_resolution and matching width/height."
        )
    tol = int(leonardo_config.get("segmentation_tolerance", 48))
    masks = parse_segmentation_image(segmented, colors=SegmentationColors(tolerance=tol))
    smooth_r = int(leonardo_config.get("mask_smooth_radius", 0))
    if smooth_r > 0:
        masks = smooth_masks(masks, radius=smooth_r)
    return masks


def finish_from_raw(
    *,
    chunk_id: str,
    painted_path: Path,
    output_dir: Path,
    placement: tuple[float, float, float, float],
    leonardo_config: dict,
    layer_name: str = "PaintedCollision",
    preview_map: bool = True,
    raw_path: Path | None = None,
) -> dict:
    """Parse segmentation_native.png or segmentation_raw.png without an API call."""
    output_dir = Path(output_dir)
    raw_path = raw_path or output_dir / "segmentation_native.png"
    if not raw_path.exists():
        raw_path = output_dir / "segmentation_raw.png"
    if not raw_path.exists():
        raise FileNotFoundError(f"No segmentation PNG in {output_dir}")

    with Image.open(painted_path) as painted:
        full_size = painted.size
        with Image.open(raw_path) as segmented:
            masks = _parse_masks_from_segmentation(segmented, full_size, leonardo_config)

        return write_collision_package(
            chunk_dir=output_dir,
            chunk_id=chunk_id,
            painted_path=painted_path,
            painted_image=painted,
            masks=masks,
            placement=placement,
            layer_name=layer_name,
            variant="leonardo_direct",
            extra_meta={"parsed_from": str(raw_path)},
            preview_map=preview_map,
        )


def run_leonardo_collision(
    *,
    chunk_id: str,
    painted_path: Path,
    output_dir: Path,
    placement: tuple[float, float, float, float],
    leonardo_config: dict[str, Any],
    mode: str = "direct",
    mechanical_config: DeriveConfig | None = None,
    prompt_path: Path | None = None,
    layer_name: str = "PaintedCollision",
    preview_map: bool = True,
) -> dict[str, Any]:
    """
    mode: 'direct' (painted chunk only) or 'hint' (painted + mechanical overlay).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    context_dir = output_dir / "context"
    context_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(painted_path) as painted:
        full_size = painted.size
        mechanical_result = None
        if mode == "hint":
            mechanical_result = derive_collision_masks(painted, mechanical_config)
            flat_path = output_dir / "mechanical_flat_hint.png"
            mechanical_flat_map(mechanical_result).save(flat_path)
            overlay_path = output_dir / "mechanical_overlay_hint.png"
            painted_with_mechanical_overlay(
                painted,
                mechanical_result,
                alpha=float(leonardo_config.get("hint_overlay_alpha", 0.55)),
            ).save(overlay_path)

        input_image, _ = build_leonardo_input(
            painted,
            mode=mode,
            mechanical_result=mechanical_result,
            hint_style=str(leonardo_config.get("hint_mode", "overlay")),
            hint_alpha=float(leonardo_config.get("hint_overlay_alpha", 0.55)),
        )

        input_path = context_dir / f"leonardo_input_{mode}.png"
        input_image.save(input_path)

        default_prompt = "collision_hint_prompt.txt" if mode == "hint" else "collision_direct_prompt.txt"
        prompt = _load_prompt(prompt_path, default_prompt)
        prompt = "\n".join(
            [
                prompt,
                "",
                f"Chunk ID: {chunk_id}",
                f"Target full map size: {full_size[0]}x{full_size[1]}",
            ]
        )

        gen_w, gen_h = full_size
        per_config = dict(leonardo_config)
        per_config["width"] = gen_w
        per_config["height"] = gen_h
        per_config["preserve_native_resolution"] = bool(
            leonardo_config.get("preserve_native_resolution", True)
        )
        per_config.pop("target_output_size", None)
        per_config.pop("skip_output_upscale", None)
        if mode == "direct":
            per_config.setdefault("reference_strength", "MID")
        else:
            per_config.setdefault("reference_strength", "HIGH")

        raw_output = output_dir / "segmentation_raw.png"
        client = make_image_client(per_config)
        try:
            gen_result = client.generate(prompt, [str(input_path)], str(raw_output))
        except ImageClientError as exc:
            err_payload = {
                "chunk_id": chunk_id,
                "variant": f"leonardo_{mode}",
                "error": str(exc),
                "input_path": str(input_path),
            }
            (context_dir / "image_result.json").write_text(json.dumps(err_payload, indent=2), encoding="utf-8")
            raise

        (context_dir / "image_result.json").write_text(
            json.dumps({**gen_result, "chunk_id": chunk_id, "mode": mode}, indent=2),
            encoding="utf-8",
        )
        (context_dir / "prompt.txt").write_text(prompt, encoding="utf-8")

        with Image.open(raw_output) as segmented:
            masks = _parse_masks_from_segmentation(segmented, full_size, leonardo_config)

        payload = write_collision_package(
            chunk_dir=output_dir,
            chunk_id=chunk_id,
            painted_path=painted_path,
            painted_image=painted,
            masks=masks,
            placement=placement,
            layer_name=layer_name,
            variant=f"leonardo_{mode}",
            extra_meta={
                "leonardo_mode": mode,
                "leonardo_input": str(input_path),
                "segmentation_raw": str(raw_output),
                "generation": gen_result,
            },
            preview_map=preview_map,
        )
        return payload
