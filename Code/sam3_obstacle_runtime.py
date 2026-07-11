"""Runtime helpers for SAM3 polygon obstacles loaded from TMX."""

from __future__ import annotations

import pygame

from Settings import DEBUG_DRAW_OBSTACLE_TINT, SAM3_TREE_TRUNK_HEIGHT_RATIO

CANOPY_CLASSES = frozenset({"tree"})

# Semi-transparent debug hues per SAM3 class (RGBA).
CLASS_TINT_RGBA: dict[str, tuple[int, int, int, int]] = {
    "tree": (48, 170, 72, 72),
    "mountain": (150, 110, 90, 68),
    "rock": (170, 170, 185, 70),
    "cliff": (130, 95, 70, 72),
    "wall": (210, 180, 90, 74),
    "ruins": (180, 120, 210, 70),
    "building": (220, 120, 80, 74),
    "boulder": (120, 120, 130, 76),
    "frozen lake": (90, 170, 230, 64),
    "?": (255, 90, 90, 58),
}
DEFAULT_TINT_RGBA = (255, 140, 60, 64)
CANOPY_OVERHEAD_RGBA = (24, 58, 32, 110)


def normalize_sam3_class(raw) -> str:
    if raw is None:
        return "?"
    text = str(raw).strip()
    return text if text else "?"


def collision_mode_for_props(props: dict) -> str:
    mode = str(props.get("collision_mode") or "").strip().lower()
    if mode in ("canopy", "solid"):
        return mode
    sam3_class = normalize_sam3_class(props.get("sam3_class"))
    if sam3_class in CANOPY_CLASSES:
        return "canopy"
    return "solid"


def tint_rgba_for_class(sam3_class: str) -> tuple[int, int, int, int]:
    return CLASS_TINT_RGBA.get(sam3_class, DEFAULT_TINT_RGBA)


def build_tint_surface(
    width: int,
    height: int,
    draw_pts: list[tuple[int, int]],
    rgba: tuple[int, int, int, int],
) -> pygame.Surface:
    surf = pygame.Surface((width, height), pygame.SRCALPHA)
    if draw_pts:
        pygame.draw.polygon(surf, rgba, draw_pts)
    return surf


def split_trunk_canopy_masks(
    mask: pygame.Mask,
    width: int,
    height: int,
    *,
    trunk_ratio: float = SAM3_TREE_TRUNK_HEIGHT_RATIO,
) -> tuple[pygame.Mask, pygame.Mask]:
    trunk_start = max(0, min(height - 1, int(height * (1.0 - trunk_ratio))))
    trunk_mask = pygame.Mask((width, height))
    canopy_mask = pygame.Mask((width, height))
    for rect in mask.get_bounding_rects():
        for y in range(rect.top, rect.bottom):
            for x in range(rect.left, rect.right):
                if mask.get_at((x, y)):
                    if y >= trunk_start:
                        trunk_mask.set_at((x, y))
                    else:
                        canopy_mask.set_at((x, y))
    return trunk_mask, canopy_mask


def invisible_collision_surface(width: int, height: int) -> pygame.Surface:
    return pygame.Surface((width, height), pygame.SRCALPHA)


def obstacle_surface_for_shape(
    *,
    width: int,
    height: int,
    draw_pts: list[tuple[int, int]],
    sam3_class: str,
    collision_mode: str,
) -> pygame.Surface:
    if DEBUG_DRAW_OBSTACLE_TINT:
        rgba = tint_rgba_for_class(sam3_class)
        if collision_mode == "canopy":
            rgba = (rgba[0], rgba[1], rgba[2], min(255, rgba[3] + 18))
        return build_tint_surface(width, height, draw_pts, rgba)
    return invisible_collision_surface(width, height)
