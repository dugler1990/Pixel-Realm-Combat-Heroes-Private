"""Chunk -> sub-level splitter.

Divides an *accepted* chunk into N playable sub-levels. The sub-run works in the CHUNK'S
OWN canvas-pixel frame (scale 1) with the generated chunk art as its "world map", so each
sub-level's package is built from the generated chunk art -- not the original world map --
and continuity/padding reuse the existing prepare/refresh/accept pipeline one tier down.

For each selected chunk: place the chunk polygon in canvas pixels, crop the accepted art to
it, ask the proposer for N sub-regions (+ flat/mountain tag), clean them into valid
``LevelSpec``s, derive adjacency via ``masks.compute_overlap``, and write a nested run:
``<output_root>/subs/<chunk>/{plan.csv, config.json, split_manifest.json, ...}``.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

from . import geometry
from .config import config_as_dict
from .coordinates import ScaledSpace, build_transform, polygon_to_local, resolve_canvas
from .masks import compute_overlap, rasterize_polygon
from .package_builder import draw_plan_overlay
from .models import Connection, LevelSpec, Point, RunConfig, SplitConfig
from .plan_loader import load_level_plan

Image.MAX_IMAGE_PIXELS = None

# The sub-run lives in the chunk art's own pixels, so no rescale of the source art.
_SUB_SCALE = "1"

def _encode_polygon(points: tuple[Point, ...]) -> str:
    return "|".join(f"{int(x)}:{int(y)}" for x, y in points)


def _scaled_contains(
    core_polygon: tuple[Point, ...],
    generation_polygon: tuple[Point, ...],
    scaled: ScaledSpace,
) -> bool:
    """True if the core polygon is contained by the generation polygon after scaling --
    the invariant ``build_level_masks`` enforces. Independent polygon simplification can
    break nesting, so the splitter checks at scale and repairs before emitting a spec."""
    core_scaled = [scaled.point(p) for p in core_polygon]
    gen_scaled = [scaled.point(p) for p in generation_polygon]
    xs = [p[0] for p in core_scaled + gen_scaled]
    ys = [p[1] for p in core_scaled + gen_scaled]
    ox, oy = min(xs), min(ys)
    size = (max(xs) - ox + 1, max(ys) - oy + 1)
    core_arr = np.asarray(rasterize_polygon(size, [(x - ox, y - oy) for x, y in core_scaled])) > 0
    gen_arr = np.asarray(rasterize_polygon(size, [(x - ox, y - oy) for x, y in gen_scaled])) > 0
    return not bool((core_arr & ~gen_arr).any())


def _region_specs(
    chunk: LevelSpec,
    chunk_polygon: tuple[Point, ...],
    regions: list,
    split_cfg: SplitConfig,
    frame_size: tuple[int, int],
    scaled: ScaledSpace,
    source_image: Path,
) -> tuple[list[LevelSpec], list[str], list[str]]:
    """Turn proposed regions (in the sub-run frame) into valid LevelSpecs (no connections
    yet). ``chunk_polygon`` is the chunk outline in that frame; ``frame_size`` is the sub-run
    canvas size. Returns (specs, tags, warnings)."""
    frame_w, frame_h = frame_size
    pad = split_cfg.overlap_buffer_px + split_cfg.crop_margin_px + 4
    left, top, right, bottom = geometry.polygon_bbox(chunk_polygon)
    ox, oy = left - pad, top - pad
    size = (right - left + 2 * pad + 1, bottom - top + 2 * pad + 1)

    def to_local(points: tuple[Point, ...]) -> tuple[Point, ...]:
        return tuple((x - ox, y - oy) for x, y in points)

    # The chunk's *visible* land = the non-black pixels of the chunk art crop. Partition THIS
    # (not the inset core polygon) so the sub-levels fill the whole image with no rim.
    with Image.open(source_image) as opened:
        src_land = np.asarray(opened.convert("RGB")).sum(axis=2) > 40
    chunk_mask = np.zeros((size[1], size[0]), dtype=bool)
    crop_h, crop_w = src_land.shape
    chunk_mask[pad : pad + crop_h, pad : pad + crop_w] = src_land
    chunk_pixels = int(chunk_mask.sum())
    min_pixels = max(64, int(0.05 * chunk_pixels / max(1, len(regions))))

    # Assign EVERY chunk pixel to a region (nearest painted seed) so the regions fill the
    # whole silhouette edge-to-edge -- no unpainted margin.
    labels = np.zeros(chunk_mask.shape, dtype=np.int32)
    for index, region in enumerate(regions, start=1):
        seed = (np.asarray(rasterize_polygon(size, to_local(region.polygon))) > 0) & chunk_mask
        labels[seed & (labels == 0)] = index
    holes = chunk_mask & (labels == 0)
    if holes.any() and (labels > 0).any():
        _, (iy, ix) = distance_transform_edt(labels == 0, return_indices=True)
        labels[holes] = labels[iy[holes], ix[holes]]

    specs: list[LevelSpec] = []
    tags: list[str] = []
    warnings: list[str] = []
    for index, region in enumerate(regions, start=1):
        core_mask = geometry.largest_connected_component((labels == index) & chunk_mask)
        if int(core_mask.sum()) < min_pixels:
            warnings.append(f"{chunk.level_id}: dropped region {index} (below min area)")
            continue
        try:
            core_local = geometry.mask_to_polygon(core_mask, epsilon_frac=0.005)
        except ValueError as exc:
            warnings.append(f"{chunk.level_id}: dropped region {index} ({exc})")
            continue
        # Generation polygon = core buffered for overlap, guaranteed to contain the exact
        # stored core at scale. Dilate the core polygon's own raster and OR it back so the
        # buffer never shrinks below core; widen and re-check until nesting holds.
        core_raster = np.asarray(rasterize_polygon(size, core_local)) > 0
        gen_local: tuple[Point, ...] | None = None
        for extra in range(0, split_cfg.overlap_buffer_px + 5):
            gen_mask = (
                geometry.dilate_mask(core_raster, split_cfg.overlap_buffer_px + extra) & chunk_mask
            ) | core_raster
            gen_mask = geometry.largest_connected_component(gen_mask)
            try:
                candidate = geometry.mask_to_polygon(gen_mask, epsilon_frac=0.005)
            except ValueError:
                continue
            if _scaled_contains(core_local, candidate, scaled):
                gen_local = candidate
                break
        if gen_local is None:
            gen_local = core_local  # safe fallback: equal polygons nest (loses the overlap band)
        core_frame = tuple((x + ox, y + oy) for x, y in core_local)
        gen_frame = tuple((x + ox, y + oy) for x, y in gen_local)

        gl, gt, gr, gb = geometry.polygon_bbox(gen_frame)
        crop_x = max(0, gl - split_cfg.crop_margin_px)
        crop_y = max(0, gt - split_cfg.crop_margin_px)
        crop_right = min(frame_w, gr + split_cfg.crop_margin_px)
        crop_bottom = min(frame_h, gb + split_cfg.crop_margin_px)
        crop_width = crop_right - crop_x
        crop_height = crop_bottom - crop_y
        if crop_width <= 0 or crop_height <= 0:
            warnings.append(f"{chunk.level_id}: dropped region {index} (degenerate crop)")
            continue

        next_index = len(specs) + 1
        proposed_name = (getattr(region, "name", "") or "").strip()
        specs.append(
            LevelSpec(
                level_id=f"{next_index:02d}",
                name=proposed_name or f"{chunk.name} {next_index}",
                region=chunk.region,
                crop_x=crop_x,
                crop_y=crop_y,
                crop_width=crop_width,
                crop_height=crop_height,
                overlap_buffer=split_cfg.overlap_buffer_px,
                core_polygon=core_frame,
                generation_polygon=gen_frame,
                connections=(),
            )
        )
        tags.append(str(getattr(region, "tag", "flat") or "flat"))
    return specs, tags, warnings


def _with_connections(specs: list[LevelSpec], scaled: ScaledSpace) -> list[LevelSpec]:
    """Symmetric land connections wherever two sub-levels' generation polygons overlap
    (the canonical adjacency test — same as prepare_run/validate_continuity)."""
    neighbors: dict[str, set[str]] = {spec.level_id: set() for spec in specs}
    for i in range(len(specs)):
        for j in range(i + 1, len(specs)):
            if compute_overlap(specs[i], specs[j], scaled) is not None:
                neighbors[specs[i].level_id].add(specs[j].level_id)
                neighbors[specs[j].level_id].add(specs[i].level_id)
    result: list[LevelSpec] = []
    for spec in specs:
        connections = tuple(
            Connection(level_id, "land") for level_id in sorted(neighbors[spec.level_id])
        )
        result.append(
            LevelSpec(
                level_id=spec.level_id,
                name=spec.name,
                region=spec.region,
                crop_x=spec.crop_x,
                crop_y=spec.crop_y,
                crop_width=spec.crop_width,
                crop_height=spec.crop_height,
                overlap_buffer=spec.overlap_buffer,
                core_polygon=spec.core_polygon,
                generation_polygon=spec.generation_polygon,
                connections=connections,
            )
        )
    return result


_CSV_COLUMNS = [
    "id",
    "name",
    "region",
    "crop_x_px",
    "crop_y_px",
    "crop_width_px",
    "crop_height_px",
    "overlap_buffer_px",
    "core_polygon_points_px",
    "generation_polygon_points_px",
    "connections",
    "tag",  # extra column: human-readable; ignored by load_level_plan
]


def _write_plan_csv(path: Path, specs: list[LevelSpec], tags: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for spec, tag in zip(specs, tags):
            writer.writerow(
                {
                    "id": spec.level_id,
                    "name": spec.name,
                    "region": spec.region,
                    "crop_x_px": spec.crop_x,
                    "crop_y_px": spec.crop_y,
                    "crop_width_px": spec.crop_width,
                    "crop_height_px": spec.crop_height,
                    "overlap_buffer_px": spec.overlap_buffer,
                    "core_polygon_points_px": _encode_polygon(spec.core_polygon),
                    "generation_polygon_points_px": _encode_polygon(spec.generation_polygon),
                    "connections": ";".join(c.level_id for c in spec.connections),
                    "tag": tag,
                }
            )


def _write_child_config(
    config: RunConfig,
    plan_csv: Path,
    child_root: Path,
    world_map: Path,
    canvas_size: tuple[int, int],
) -> Path:
    """A normal world-level config for the nested run: the generated chunk art as its world
    map, scale 1 (art is already at final resolution), an explicit canvas the size of that
    art, its own plan + output root, same renderer/generation as the parent, no split."""
    child = config_as_dict(config)
    child["level_plan"] = str(plan_csv)
    child["output_root"] = str(child_root)
    child["world_map"] = str(world_map)
    child["scale"] = {"pixels_per_world_pixel": _SUB_SCALE}
    child["canvas"] = {
        "mode": "explicit",
        "width": int(canvas_size[0]),
        "height": int(canvas_size[1]),
        "placement": "top_left",
        "margin": 0,
    }
    child.pop("split", None)
    config_path = child_root / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(child, indent=2), encoding="utf-8")
    return config_path


def split_chunk(
    config: RunConfig,
    chunk: LevelSpec,
    proposer,
    parent_scaled: ScaledSpace,
    parent_canvas_size: tuple[int, int],
) -> dict[str, Any]:
    from .region_proposer import ProposeRequest

    split_cfg = config.split or SplitConfig()
    root = config.output_root
    accepted = root / "levels" / chunk.level_id / "accepted" / "image.png"
    if not accepted.is_file():
        raise ValueError(
            f"chunk {chunk.level_id} must be generated and accepted before splitting "
            f"(missing {accepted})"
        )

    # The chunk outline in the parent CANVAS frame = the sub-run's coordinate frame.
    transform = build_transform(chunk, parent_scaled, config.canvas, parent_canvas_size)
    canvas_poly = polygon_to_local(chunk.core_polygon, parent_scaled, transform)
    frame_bbox = geometry.polygon_bbox(canvas_poly)

    child_root = root / "subs" / chunk.level_id
    child_root.mkdir(parents=True, exist_ok=True)
    source_image = child_root / "proposer_source.png"
    cl, ct, cr, cb = frame_bbox
    with Image.open(accepted) as img:
        img.convert("RGBA").crop((cl, ct, cr + 1, cb + 1)).save(source_image)

    area = geometry.polygon_area(chunk.core_polygon)  # bucket by real (world) area
    n = split_cfg.count_for_area(area)
    regions = proposer.propose(
        ProposeRequest(
            chunk_id=chunk.level_id,
            chunk_polygon=canvas_poly,
            chunk_art=source_image,
            n=n,
            criteria=split_cfg.criteria,
            world_bbox=frame_bbox,
        )
    )

    sub_scaled = ScaledSpace(_SUB_SCALE)
    specs, tags, warnings = _region_specs(
        chunk, canvas_poly, regions, split_cfg, parent_canvas_size, sub_scaled, source_image
    )
    if not specs:
        raise ValueError(f"chunk {chunk.level_id}: no usable sub-levels were produced")
    specs = _with_connections(specs, sub_scaled)

    plan_csv = child_root / "plan.csv"
    _write_plan_csv(plan_csv, specs, tags)
    load_level_plan(plan_csv, parent_canvas_size)  # self-check against the real loader
    config_path = _write_child_config(config, plan_csv, child_root, accepted, parent_canvas_size)
    overlay_path = child_root / "division_overlay.png"
    with Image.open(accepted) as art:
        draw_plan_overlay(art.convert("RGBA"), {spec.level_id: spec for spec in specs}).save(overlay_path)

    manifest = {
        "source_chunk": chunk.level_id,
        "source_name": chunk.name,
        "chunk_area": area,
        "sub_level_count": len(specs),
        "requested_count": n,
        "source_art": str(accepted),
        "child_config": str(config_path),
        "child_plan": str(plan_csv),
        "division_overlay": str(overlay_path),
        "sub_levels": [
            {"id": spec.level_id, "name": spec.name, "tag": tag}
            for spec, tag in zip(specs, tags)
        ],
        "warnings": warnings,
    }
    (child_root / "split_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def split_run(config: RunConfig, chunk_ids: list[str] | None = None) -> dict[str, Any]:
    from .region_proposer import make_region_proposer

    split_cfg = config.split or SplitConfig()
    levels = load_level_plan(config.level_plan)
    parent_scaled = ScaledSpace(config.scale)
    parent_canvas_size = resolve_canvas(config.canvas, levels, parent_scaled)
    proposer = make_region_proposer(split_cfg.proposer)

    selected = [cid.zfill(2) for cid in chunk_ids] if chunk_ids else list(levels)
    unknown = [cid for cid in selected if cid not in levels]
    if unknown:
        raise ValueError(f"unknown chunks: {', '.join(unknown)}")

    results = [
        split_chunk(config, levels[cid], proposer, parent_scaled, parent_canvas_size)
        for cid in selected
    ]
    return {"chunks": selected, "results": results}
