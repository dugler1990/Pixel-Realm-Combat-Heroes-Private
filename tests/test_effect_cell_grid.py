import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pygame
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from effect_cell_grid import EffectCellGrid  # noqa: E402
from Entity import Entity  # noqa: E402


CELL = 32
WORLD_W = 320
WORLD_H = 320


def _area(x, y, w, h):
    return SimpleNamespace(rect=pygame.Rect(x, y, w, h))


def _grid_with_area(x, y, w, h):
    return EffectCellGrid.build([_area(x, y, w, h)], CELL, WORLD_W, WORLD_H)


def test_marks_cells_for_effect_rect():
    grid = _grid_with_area(40, 40, 64, 64)
    assert grid.intersects_rect(pygame.Rect(50, 50, 16, 16))
    assert not grid.intersects_rect(pygame.Rect(200, 200, 16, 16))


def test_intersects_rect_covers_entity_footprint():
    grid = _grid_with_area(0, 0, CELL, CELL)
    spanning = pygame.Rect(CELL - 4, CELL - 4, 8, 8)
    assert grid.intersects_rect(spanning)


def _entity_at(x, y, w=16, h=16):
    entity = Entity.__new__(Entity)
    entity.id = 1
    entity.rect = pygame.Rect(x, y, w, h)
    entity.active_effects = {}
    entity.mask = None
    return entity


def test_check_effects_skips_when_outside_grid():
    grid = _grid_with_area(0, 0, CELL, CELL)
    entity = _entity_at(200, 200)
    mock_tree = mock.Mock()
    mock_tree.hit = mock.Mock(return_value=[])
    trees = {"layer": mock_tree}

    entity.check_effects(trees, grid)

    mock_tree.hit.assert_not_called()


def test_check_effects_runs_when_active_effects_even_outside_grid():
    grid = _grid_with_area(0, 0, CELL, CELL)
    entity = _entity_at(200, 200)
    entity.active_effects = {("fx_1", "heat"): mock.Mock()}
    mock_tree = mock.Mock()
    mock_tree.hit = mock.Mock(return_value=[])
    trees = {"layer": mock_tree}

    entity.check_effects(trees, grid)

    mock_tree.hit.assert_called_once()
