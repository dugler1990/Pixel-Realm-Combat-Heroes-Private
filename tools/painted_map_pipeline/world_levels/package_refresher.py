from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .config import load_config
from .coordinates import ScaledSpace, build_transform
from .masks import overlap_on_canvas, pending_mask, shared_strip
from .models import LevelState
from .package_builder import level_paths
from .plan_loader import load_level_plan
from .state_store import append_event, atomic_write_json, read_json, sha256_file, utc_now

Image.MAX_IMAGE_PIXELS = None


def _load_context(root: Path):
    config = load_config(root / "config.resolved.json")
    run = read_json(root / "run.json")
    levels = load_level_plan(config.level_plan, tuple(run["world_size"]))
    scaled = ScaledSpace(config.scale)
    canvas_size = tuple(int(value) for value in run["canvas_size"])
    transforms = {
        level_id: build_transform(level, scaled, config.canvas, canvas_size)
        for level_id, level in levels.items()
    }
    return config, run, levels, scaled, canvas_size, transforms


def refresh_level(
    root: str | Path,
    level_id: str,
    *,
    force: bool = False,
    refine: bool = False,
) -> dict[str, Any]:
    """Rebuild a level's generation input from the current accepted neighbours.

    ``force`` reopens a level that is already accepted. The pipeline treats accepted as
    frozen, which is right going forward but blocks every backwards operation -- fixing a
    defect in finished art, or running a refine pass over it.

    ``refine`` starts from the level's own accepted image rather than the soft world-map
    template, so a second pass only has to align the existing painting to its padding
    instead of inventing detail and matching a strip at the same time.
    """
    root_path = Path(root).resolve()
    _, run, levels, scaled, canvas_size, transforms = _load_context(root_path)
    level_id = level_id.zfill(2)
    if level_id not in levels:
        raise KeyError(f"unknown level: {level_id}")
    target_state = run["levels"][level_id]["state"]
    if target_state == LevelState.ACCEPTED.value and not force:
        return {"level_id": level_id, "skipped": "accepted"}

    target = levels[level_id]
    target_paths = level_paths(root_path, level_id)
    target_manifest = read_json(target_paths["manifest"])
    with Image.open(target_paths["dense_template"]) as opened:
        generation_input = opened.convert("RGBA")
    with Image.open(target_paths["generation_mask"]) as opened:
        generation_mask = opened.convert("L")
    if refine:
        # "Start from the finished art instead of the soft template" -- in canvas space that
        # is the dense template with the accepted image composited inside the polygon. Built
        # the same way whichever renderer is in use: one masks it back to the silhouette, the
        # other crops it to a frame, and neither needs a branch here.
        accepted_path = target_paths["root"] / "accepted" / "image.png"
        if not accepted_path.is_file():
            raise FileNotFoundError(
                f"level {level_id} has no accepted image to refine: {accepted_path}"
            )
        with Image.open(accepted_path) as opened:
            generation_input = Image.composite(
                opened.convert("RGBA"), generation_input, generation_mask
            )
    locked_pixels = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    locked_mask_array = np.zeros((canvas_size[1], canvas_size[0]), dtype=bool)
    locked_sources: list[dict[str, Any]] = []

    # Every accepted level, not the declared connections. A cell's margin reaches 150px past
    # its core, so it also overlaps the four levels it meets only at a corner -- which the
    # connection list, being edge adjacency, never names. Driving padding from that list is
    # what leaves a hard edge at every four-way junction. Levels that do not actually overlap
    # cost nothing: shared_strip returns None for them.
    #
    # Sorted by acceptance index so the first level accepted keeps whatever it painted, and
    # the caller's mask against already-locked pixels does the rest.
    accepted_neighbors = sorted(
        (int(entry.get("acceptance_index", 2**31)), other_id)
        for other_id, entry in run["levels"].items()
        if other_id != level_id and entry.get("state") == LevelState.ACCEPTED.value
    )

    overlaps_dir = target_paths["root"] / "masks" / "overlaps"
    overlaps_dir.mkdir(parents=True, exist_ok=True)
    for _, neighbor_id in accepted_neighbors:
        # Only the neighbour's own half of the overlap. Taking the whole thing would hand
        # this level a fixed rendering of 150px of its own core.
        overlap = shared_strip(target, levels[neighbor_id], scaled)
        if overlap is None:
            continue
        neighbor_paths = level_paths(root_path, neighbor_id)

        target_overlap = overlap_on_canvas(overlap, transforms[level_id])
        target_overlap.save(overlaps_dir / f"{neighbor_id}.png")

        source_overlaps_dir = neighbor_paths["root"] / "masks" / "overlaps"
        source_overlaps_dir.mkdir(parents=True, exist_ok=True)
        source_overlap = overlap_on_canvas(overlap, transforms[neighbor_id])
        source_overlap.save(source_overlaps_dir / f"{level_id}.png")

        overlap_array = np.asarray(target_overlap) > 0
        available = overlap_array & ~locked_mask_array
        if not np.any(available):
            continue

        accepted_path = neighbor_paths["root"] / "accepted" / "image.png"
        if not accepted_path.is_file():
            raise FileNotFoundError(f"accepted image missing for level {neighbor_id}: {accepted_path}")
        with Image.open(accepted_path) as opened:
            neighbor_image = opened.convert("RGBA")
        source_x, source_y = transforms[neighbor_id].global_to_local(
            overlap.global_box[0], overlap.global_box[1]
        )
        target_x, target_y = transforms[level_id].global_to_local(
            overlap.global_box[0], overlap.global_box[1]
        )
        source_region = neighbor_image.crop(
            (source_x, source_y, source_x + overlap.width, source_y + overlap.height)
        )
        available_region = available[
            target_y : target_y + overlap.height,
            target_x : target_x + overlap.width,
        ]
        paste_mask = Image.fromarray(available_region.astype(np.uint8) * 255, mode="L")
        locked_pixels.paste(source_region, (target_x, target_y), paste_mask)
        generation_input.paste(source_region, (target_x, target_y), paste_mask)
        locked_mask_array |= available
        locked_sources.append(
            {
                "neighbor_id": neighbor_id,
                "global_box": list(overlap.global_box),
                "pixel_count": int(np.count_nonzero(available)),
                "accepted_hash": sha256_file(accepted_path),
            }
        )

    locked_mask = Image.fromarray(locked_mask_array.astype(np.uint8) * 255, mode="L")
    # generation_input.png stays dense on purpose. Cutting it to the polygon is how the warp
    # renderer presents a level, not a property of the level, so it happens in that renderer
    # instead -- which is what lets every stage up to here be renderer-blind.
    locked_pixels.save(target_paths["locked_pixels"])
    locked_mask.save(target_paths["locked_mask"])
    pending_mask(generation_mask, locked_mask).save(target_paths["pending_mask"])
    generation_input.save(target_paths["generation_input"])

    new_hash = sha256_file(target_paths["generation_input"])
    previous_hash = target_manifest.get("hashes", {}).get("generation_input")
    revision = int(target_manifest.get("context_revision", 0))
    if new_hash != previous_hash:
        revision += 1
    target_manifest.update(
        {
            "state": LevelState.READY.value,
            "locked_sources": locked_sources,
            "context_revision": revision,
            "updated_at": utc_now(),
        }
    )
    target_manifest.setdefault("hashes", {}).update(
        {
            "generation_input": new_hash,
            "locked_pixels": sha256_file(target_paths["locked_pixels"]),
            "locked_mask": sha256_file(target_paths["locked_mask"]),
        }
    )
    atomic_write_json(target_paths["manifest"], target_manifest)
    run["levels"][level_id].update(
        {
            "state": LevelState.READY.value,
            "context_revision": revision,
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(root_path / "run.json", run)
    append_event(
        root_path,
        "level_refreshed",
        level_id=level_id,
        context_revision=revision,
        locked_sources=[item["neighbor_id"] for item in locked_sources],
    )
    return {
        "level_id": level_id,
        "state": LevelState.READY.value,
        "context_revision": revision,
        "locked_sources": locked_sources,
    }


def refresh_neighbors(
    root: str | Path,
    accepted_level_id: str,
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Push this level's accepted pixels into its neighbours.

    Accepted neighbours are skipped unless ``force``: normally their art is finished and
    must not shift underneath them, but after correcting a defect they do need the fix.
    """
    root_path = Path(root).resolve()
    _, run, levels, scaled, _, _ = _load_context(root_path)
    level_id = accepted_level_id.zfill(2)
    results = []
    # Whoever this level's pixels can reach, which is anyone it overlaps -- including the
    # levels it meets only at a corner. Pushing only to declared connections would leave those
    # levels holding a stale input that never learns this one was accepted.
    for other_id in sorted(run["levels"]):
        if other_id == level_id:
            continue
        if shared_strip(levels[other_id], levels[level_id], scaled) is None:
            continue
        neighbor_accepted = run["levels"][other_id]["state"] == LevelState.ACCEPTED.value
        if not neighbor_accepted or force:
            results.append(refresh_level(root_path, other_id, force=force))
    return results


def refresh_levels(root: str | Path, level_ids: list[str] | None = None) -> list[dict[str, Any]]:
    root_path = Path(root).resolve()
    _, run, _, _, _, _ = _load_context(root_path)
    selected = level_ids or sorted(run["levels"])
    return [refresh_level(root_path, level_id) for level_id in selected]
