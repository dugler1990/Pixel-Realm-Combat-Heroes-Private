"""Pathfinding footprint from unit collision masks."""

import os

import pygame

from Support import (
    frames_to_masks,
    import_folder,
    mask_footprint_size,
    normalize_animation_frames,
)

_REPRESENTATIVE_MASK_CACHE = {}

_RTS_WORKER_MONSTERS = ("eskimo_worker", "jungle_worker")


def rts_worker_monster_names():
    return _RTS_WORKER_MONSTERS


def _load_move_frame(monster_name):
    from rts.assets import load_sprite

    main_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "Graphics", "Monsters", monster_name, "move")
    )
    frames = import_folder(main_path)
    if not frames:
        frames = [load_sprite(f"worker_{monster_name.split('_')[0]}")]
    if monster_name == "eskimo_worker":
        frames = normalize_animation_frames(frames)
    return frames[0]


def representative_monster_mask(monster_name):
    name = str(monster_name or "").strip()
    if not name:
        return None
    if name in _REPRESENTATIVE_MASK_CACHE:
        return _REPRESENTATIVE_MASK_CACHE[name]
    frame = _load_move_frame(name)
    masks = frames_to_masks([frame])
    mask = masks[0] if masks else None
    _REPRESENTATIVE_MASK_CACHE[name] = mask
    return mask


def pathfinding_footprint_for_monster(monster_name):
    rep_mask = representative_monster_mask(monster_name)
    size = mask_footprint_size(rep_mask)
    if size is None:
        return (32, 32)
    return size


def pathfinding_footprint_for_unit(unit):
    monster = getattr(unit, "monster_name", None) or "eskimo_worker"
    return pathfinding_footprint_for_monster(monster)
