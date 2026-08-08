from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .config import RunConfig, config_as_dict
from .coordinates import ScaledSpace, build_transform, resolve_canvas
from .frames import Frame, constraints_for, derive_frame, world_box_covering
from .masks import build_level_masks, compute_overlap, outside_mask, pending_mask
from .models import LevelSpec, LevelState, LevelTransform
from .plan_loader import load_level_plan
from .state_store import append_event, atomic_write_json, read_json, sha256_file, sha256_json, utc_now

Image.MAX_IMAGE_PIXELS = None


def _resample(name: str) -> int:
    values = getattr(Image, "Resampling", Image)
    return getattr(values, name.upper())


def _save_mask(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _level_paths(root: Path, level_id: str) -> dict[str, Path]:
    level_root = root / "levels" / level_id
    return {
        "root": level_root,
        "manifest": level_root / "manifest.json",
        "source_crop": level_root / "source" / "world_crop.png",
        # The soft world map over the whole frame, not cut to the polygon. Every renderer
        # builds its input from this; masking to the silhouette is a presentation choice that
        # belongs to the renderer that wants it.
        "dense_template": level_root / "dense_template.png",
        "generation_input": level_root / "generation_input.png",
        "core_mask": level_root / "masks" / "core.png",
        "generation_mask": level_root / "masks" / "generation.png",
        "outside_mask": level_root / "masks" / "outside.png",
        "pending_mask": level_root / "masks" / "pending.png",
        "locked_pixels": level_root / "locked" / "canonical_overlap.png",
        "locked_mask": level_root / "locked" / "canonical_overlap_mask.png",
        "locator": level_root / "locator.png",
    }


def level_paths(root: str | Path, level_id: str) -> dict[str, Path]:
    return _level_paths(Path(root), level_id)


def _draw_locator(world: Image.Image, level: LevelSpec) -> Image.Image:
    locator = world.convert("RGBA")
    draw = ImageDraw.Draw(locator, "RGBA")
    draw.polygon(level.generation_polygon, fill=(0, 180, 255, 50), outline=(0, 210, 255, 255), width=2)
    draw.polygon(level.core_polygon, fill=(255, 210, 0, 45), outline=(255, 225, 0, 255), width=2)
    left, top, right, bottom = level.crop_box
    draw.rectangle((left, top, right - 1, bottom - 1), outline=(255, 255, 255, 255), width=2)
    return locator


def _draw_plan_overlay(world: Image.Image, levels: dict[str, LevelSpec]) -> Image.Image:
    overlay = world.convert("RGBA")
    draw = ImageDraw.Draw(overlay, "RGBA")
    for level in levels.values():
        draw.polygon(level.generation_polygon, fill=(0, 170, 255, 22), outline=(0, 200, 255, 170), width=1)
        draw.polygon(level.core_polygon, fill=(255, 190, 0, 20), outline=(255, 225, 0, 220), width=2)
        x = sum(point[0] for point in level.core_polygon) // len(level.core_polygon)
        y = sum(point[1] for point in level.core_polygon) // len(level.core_polygon)
        draw.text((x, y), level.level_id, fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0, 255))
    return overlay


def _dense_canvas(
    config: RunConfig,
    world: Image.Image,
    scaled: ScaledSpace,
    transform: LevelTransform,
    frame: Frame,
    canvas_size: tuple[int, int],
) -> Image.Image:
    """The world map painted across the whole frame, not just the level's own crop.

    The frame is usually a little wider than the crop, so this pulls in the neighbouring
    world map to fill it rather than padding with black -- black in the frame is what makes a
    model crop to the content and reframe. Where the world image runs out, the deficit stays
    ``outside_color``; that is bounded and only happens at the map's own edges.
    """
    world_box = world_box_covering(frame, transform, scaled, world.size)
    left, top, right, bottom = world_box
    crop = world.crop(world_box).convert("RGBA")
    size = (scaled.span(left, right - left), scaled.span(top, bottom - top))
    resized = crop.resize(size, _resample(config.source_resampling))
    canvas = Image.new("RGBA", canvas_size, config.outside_color)
    canvas.paste(resized, transform.global_to_local(scaled.coordinate(left), scaled.coordinate(top)))
    return canvas


def prepare_level(
    config: RunConfig,
    world: Image.Image,
    level: LevelSpec,
    scaled: ScaledSpace,
    canvas_size: tuple[int, int],
    previous_state: str = LevelState.UNPREPARED.value,
) -> dict[str, Any]:
    paths = _level_paths(config.output_root, level.level_id)
    for directory in ("source", "masks/overlaps", "locked", "jobs", "attempts", "accepted"):
        (paths["root"] / directory).mkdir(parents=True, exist_ok=True)

    transform = build_transform(level, scaled, config.canvas, canvas_size)
    frame = derive_frame(transform, constraints_for(config.generation), level_id=level.level_id)
    crop = world.crop(level.crop_box).convert("RGBA")
    crop.save(paths["source_crop"])
    dense = _dense_canvas(config, world, scaled, transform, frame, canvas_size)

    core, generation = build_level_masks(level, scaled, transform)
    outside = outside_mask(generation)
    locked_pixels = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    locked_mask = Image.new("L", canvas_size, 0)

    dense.save(paths["dense_template"])
    dense.save(paths["generation_input"])
    _save_mask(core, paths["core_mask"])
    _save_mask(generation, paths["generation_mask"])
    _save_mask(outside, paths["outside_mask"])
    _save_mask(pending_mask(generation, locked_mask), paths["pending_mask"])
    locked_pixels.save(paths["locked_pixels"])
    locked_mask.save(paths["locked_mask"])
    _draw_locator(world, level).save(paths["locator"])

    state = previous_state if previous_state == LevelState.ACCEPTED.value else LevelState.PREPARED.value
    manifest = {
        "schema_version": 1,
        "level_id": level.level_id,
        "name": level.name,
        "region": level.region,
        "state": state,
        "crop_box_world": list(level.crop_box),
        "core_polygon_world": [list(point) for point in level.core_polygon],
        "generation_polygon_world": [list(point) for point in level.generation_polygon],
        "overlap_buffer_source_px": level.overlap_buffer,
        "connections": [{"level_id": item.level_id, "kind": item.kind} for item in level.connections],
        "transform": transform.as_dict(),
        "frame": frame.as_dict(),
        "canvas_size": list(canvas_size),
        "paths": {key: str(value) for key, value in paths.items() if key != "root"},
        "hashes": {
            "world_map": sha256_file(config.world_map),
            "dense_template": sha256_file(paths["dense_template"]),
            "generation_mask": sha256_file(paths["generation_mask"]),
        },
        "context_revision": 0,
        "locked_sources": [],
        "attempt_count": 0,
        "updated_at": utc_now(),
    }
    atomic_write_json(paths["manifest"], manifest)
    return manifest


def prepare_run(config: RunConfig) -> dict[str, Any]:
    with Image.open(config.world_map) as opened:
        world = opened.convert("RGBA")
    levels = load_level_plan(config.level_plan, world.size)
    scaled = ScaledSpace(config.scale)
    canvas_size = resolve_canvas(config.canvas, levels, scaled)
    config_dict = config_as_dict(config)
    config_hash = sha256_json(config_dict)
    config.output_root.mkdir(parents=True, exist_ok=True)
    run_path = config.output_root / "run.json"
    existing = read_json(run_path) if run_path.exists() else {}
    if existing and existing.get("renderer", "warp") != config.renderer:
        # Levels are prepared differently per renderer -- the frame geometry in each manifest
        # is derived from it -- and prepare reuses manifests that already exist. Switching in
        # place would leave every level carrying geometry from the other method. Comparing
        # two methods means two output roots, not one root edited back and forth.
        raise ValueError(
            f"run was prepared with renderer {existing.get('renderer', 'warp')!r} and the "
            f"config now says {config.renderer!r}; use a separate output_root per renderer"
        )
    if existing and existing.get("config_hash") != config_hash:
        accepted = [
            level_id
            for level_id, entry in existing.get("levels", {}).items()
            if entry.get("state") == LevelState.ACCEPTED.value
        ]
        if accepted:
            raise ValueError(
                "configuration changed while accepted levels exist; use a new output_root "
                f"or migrate accepted levels explicitly ({', '.join(accepted)})"
            )

    for level in levels.values():
        for connection in level.connections:
            if connection.kind == "boat" or level.level_id > connection.level_id:
                continue
            if compute_overlap(level, levels[connection.level_id], scaled) is None:
                raise ValueError(f"land connection {level.level_id}-{connection.level_id} has no generation overlap")

    atomic_write_json(config.output_root / "config.resolved.json", config_dict)
    _draw_plan_overlay(world, levels).save(config.output_root / "plan_validation_overlay.png")
    manifests: dict[str, Any] = {}
    run_levels: dict[str, Any] = {}
    for level_id, level in levels.items():
        previous = existing.get("levels", {}).get(level_id, {})
        existing_manifest_path = _level_paths(config.output_root, level_id)["manifest"]
        if previous and existing_manifest_path.is_file():
            manifest = read_json(existing_manifest_path)
        else:
            manifest = prepare_level(
                config,
                world,
                level,
                scaled,
                canvas_size,
                previous_state=str(previous.get("state") or LevelState.UNPREPARED.value),
            )
        manifests[level_id] = manifest
        run_levels[level_id] = {
            **previous,
            "name": level.name,
            "region": level.region,
            "state": manifest["state"],
            "manifest": str(_level_paths(config.output_root, level_id)["manifest"]),
            "updated_at": utc_now(),
        }
    run = {
        "schema_version": 1,
        "config_hash": config_hash,
        "renderer": config.renderer,
        "config_path": str(config.output_root / "config.resolved.json"),
        "world_size": list(world.size),
        "canvas_size": list(canvas_size),
        "scale": config.scale,
        "acceptance_counter": int(existing.get("acceptance_counter", 0)),
        "levels": run_levels,
        "updated_at": utc_now(),
    }
    atomic_write_json(run_path, run)
    atomic_write_json(
        config.output_root / "plan_validation.json",
        {
            "valid": True,
            "level_count": len(levels),
            "world_size": list(world.size),
            "canvas_size": list(canvas_size),
            "config_hash": config_hash,
        },
    )
    append_event(config.output_root, "run_prepared", level_count=len(levels), config_hash=config_hash)
    return run
