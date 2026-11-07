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

import legion_ui  # noqa: E402
from ImageCache import ImageCache  # noqa: E402
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
def fresh_kit():
    """Each test starts with no kept text or pieces, so the first draw renders and the second
    must not."""
    ImageCache.clear()
    legion_ui._KITS.clear()
    yield
    ImageCache.clear()
    legion_ui._KITS.clear()


@pytest.fixture
def rendered(monkeypatch):
    """Every string legion_ui renders, in order."""
    calls = []
    real = legion_ui.render_text

    def counting(font, text, colour, spacing=0, shadow=True):
        calls.append(text)
        return real(font, text, colour, spacing, shadow)

    monkeypatch.setattr(legion_ui, "render_text", counting)
    return calls


def test_ui_show_exp_renders_only_on_value_change(pygame_headless, rendered):
    from UI import UI

    ui = UI(CPUBackend(pygame_headless))
    ui.show_exp(100)
    ui.show_exp(100)
    assert rendered == ["100"]

    ui.show_exp(101)
    assert rendered == ["100", "101"]


def test_ui_show_level_renders_only_on_value_change(pygame_headless, rendered):
    from UI import UI

    ui = UI(CPUBackend(pygame_headless))
    ui.show_level(3)
    ui.show_level(3)
    assert rendered == ["LEVEL 3"]

    ui.show_level(4)
    assert rendered == ["LEVEL 3", "LEVEL 4"]


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


def test_draw_belt_hud_label_cache(pygame_headless, rendered):
    player = SimpleNamespace(has_belt=True, belt_capacity=BELT_SLOT_COUNT)
    inventory = _belt_inventory(*([None] * BELT_SLOT_COUNT))
    backend = CPUBackend(pygame_headless)
    draw_belt_hud(backend, player, inventory)
    draw_belt_hud(backend, player, inventory)

    assert rendered == [str(i + 1) for i in range(BELT_SLOT_COUNT)]


def test_draw_belt_hud_qty_cache_shared_across_slots(pygame_headless, rendered):
    player = SimpleNamespace(has_belt=True, belt_capacity=BELT_SLOT_COUNT)
    inventory = _belt_inventory(3, 3, None, None)
    backend = CPUBackend(pygame_headless)
    draw_belt_hud(backend, player, inventory)
    draw_belt_hud(backend, player, inventory)

    # 4 slot numbers + 1 shared count for the two slots both showing 3
    assert sorted(rendered) == sorted([str(i + 1) for i in range(BELT_SLOT_COUNT)] + ["3"])


def test_draw_belt_hud_reuses_one_lock_surface(pygame_headless):
    player = SimpleNamespace(has_belt=True, belt_capacity=1)
    inventory = _belt_inventory(*([None] * BELT_SLOT_COUNT))
    backend = CPUBackend(pygame_headless)
    kit = legion_ui.kit_for(backend)
    blitted = []
    real_blit = backend.blit

    def recording_blit(surface, dest, **kw):
        blitted.append(surface)
        return real_blit(surface, dest, **kw)

    backend.blit = recording_blit
    draw_belt_hud(backend, player, inventory)
    draw_belt_hud(backend, player, inventory)
    side = kit.px(48)
    lock = kit.dimmer(side, side)
    # The three locked slots, drawn twice, all use the one kept shade.
    assert sum(1 for s in blitted if s is lock) == 2 * (BELT_SLOT_COUNT - 1)
