"""Tests for SAM3 obstacle runtime helpers."""

import pygame

from sam3_obstacle_runtime import (
    collision_mode_for_props,
    split_trunk_canopy_masks,
)


def test_collision_mode_defaults_tree_to_canopy():
    assert collision_mode_for_props({"sam3_class": "tree"}) == "canopy"


def test_collision_mode_respects_explicit_property():
    assert collision_mode_for_props({"sam3_class": "tree", "collision_mode": "solid"}) == "solid"


def test_split_trunk_canopy_masks():
    surf = pygame.Surface((10, 20), pygame.SRCALPHA)
    pygame.draw.rect(surf, (255, 255, 255, 255), (2, 2, 6, 16))
    mask = pygame.mask.from_surface(surf)
    trunk, canopy = split_trunk_canopy_masks(mask, 10, 20, trunk_ratio=0.2)
    assert trunk.count() > 0
    assert canopy.count() > 0
    assert trunk.count() + canopy.count() == mask.count()
