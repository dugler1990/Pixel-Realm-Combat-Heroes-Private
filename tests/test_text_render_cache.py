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

import Inventory  # noqa: E402
from Inventory import (  # noqa: E402
    BELT_SLOT_COUNT,
    InventorySlot,
    draw_belt_hud,
)
from render_backend import CPUBackend  # noqa: E402
from tmx_layout_manager import LayoutManager  # noqa: E402


@pytest.fixture(autouse=True)
def pygame_headless():
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    yield screen


@pytest.fixture(autouse=True)
def clear_belt_text_caches():
    Inventory._BELT_HUD_FONT = None
    Inventory._BELT_LABEL_SURFACES = None
    Inventory._BELT_QTY_SURFACES.clear()
    yield
    Inventory._BELT_HUD_FONT = None
    Inventory._BELT_LABEL_SURFACES = None
    Inventory._BELT_QTY_SURFACES.clear()


def test_ui_show_exp_renders_only_on_value_change(pygame_headless):
    render_calls = []

    def fake_render(text, antialias, color):
        render_calls.append(text)
        return pygame.Surface((40, 20), pygame.SRCALPHA)

    mock_font = mock.Mock()
    mock_font.render.side_effect = fake_render

    from UI import UI

    ui = UI.__new__(UI)
    ui.backend = CPUBackend(pygame_headless)
    ui.font = mock_font
    ui._exp_value = None
    ui._exp_surface = None

    ui.show_exp(100)
    ui.show_exp(100)
    assert render_calls == ["100"]

    ui.show_exp(101)
    assert render_calls == ["100", "101"]


def test_ui_show_level_renders_only_on_value_change(pygame_headless):
    render_calls = []

    def fake_render(text, antialias, color):
        render_calls.append(text)
        return pygame.Surface((60, 20), pygame.SRCALPHA)

    mock_font = mock.Mock()
    mock_font.render.side_effect = fake_render

    from UI import UI

    ui = UI.__new__(UI)
    ui.backend = CPUBackend(pygame_headless)
    ui.font = mock_font
    ui._level_value = None
    ui._level_surface = None

    ui.show_level(3)
    ui.show_level(3)
    assert render_calls == ["Level: 3"]

    ui.show_level(4)
    assert render_calls == ["Level: 3", "Level: 4"]


def test_display_time_renders_only_on_string_change(pygame_headless):
    render_calls = []

    def fake_render(text, antialias, color):
        render_calls.append(text)
        return pygame.Surface((40, 20), pygame.SRCALPHA)

    mock_font = mock.Mock()
    mock_font.render.side_effect = fake_render

    lm = LayoutManager.__new__(LayoutManager)
    lm.start_ticks = 0
    lm._time_font = mock_font
    lm._time_string = None
    lm._time_surface = None

    backend = CPUBackend(pygame_headless)
    with mock.patch("pygame.time.get_ticks", return_value=500):
        lm.display_time(backend)
        lm.display_time(backend)
    assert render_calls == ["00:00"]

    with mock.patch("pygame.time.get_ticks", return_value=1500):
        lm.display_time(backend)
    assert render_calls == ["00:00", "00:01"]


def _belt_inventory(*quantities):
    slots = [
        InventorySlot(pygame.Rect(0, 0, 36, 36), "belt")
        for _ in range(BELT_SLOT_COUNT)
    ]
    item = SimpleNamespace(image_path=None)
    for slot, qty in zip(slots, quantities):
        if qty is not None:
            slot.item = item
            slot.quantity = qty
    return SimpleNamespace(belt_start_index=0, slots=slots)


def test_draw_belt_hud_label_cache(pygame_headless):
    player = SimpleNamespace(has_belt=True, belt_capacity=BELT_SLOT_COUNT)
    inventory = _belt_inventory(*([None] * BELT_SLOT_COUNT))
    render_calls = []

    def counting_render(text, antialias, color):
        render_calls.append(text)
        return pygame.Surface((8, 8), pygame.SRCALPHA)

    with mock.patch("pygame.font.Font") as font_cls:
        font_cls.return_value.render.side_effect = counting_render
        backend = CPUBackend(pygame_headless)
        draw_belt_hud(backend, player, inventory)
        draw_belt_hud(backend, player, inventory)

    assert len(render_calls) == BELT_SLOT_COUNT


def test_draw_belt_hud_qty_cache_shared_across_slots(pygame_headless):
    player = SimpleNamespace(has_belt=True, belt_capacity=BELT_SLOT_COUNT)
    inventory = _belt_inventory(3, 3, None, None)
    render_calls = []

    def counting_render(text, antialias, color):
        render_calls.append(text)
        return pygame.Surface((8, 8), pygame.SRCALPHA)

    with mock.patch("pygame.font.Font") as font_cls:
        font_cls.return_value.render.side_effect = counting_render
        backend = CPUBackend(pygame_headless)
        draw_belt_hud(backend, player, inventory)
        draw_belt_hud(backend, player, inventory)

    # 4 slot labels + 1 shared qty surface for two slots both showing 3
    assert len(render_calls) == BELT_SLOT_COUNT + 1
