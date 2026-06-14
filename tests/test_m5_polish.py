"""M5 polish: 'network' debug-logging channel + 'Multiplayer (dev)' menu entry.

Covers the wiring that's cheap to unit-test. The full menu->level->connect path
can't run headlessly (dummy-SDL fires a spurious QUIT and pygame.quit() hangs),
so that stays a human check; here we verify the channel registration/default and
that selecting the menu entry arms the multiplayer bootstrap.
"""

import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()
pygame.font.init()

import game_logging  # noqa: E402
from StartMenu import StartMenu  # noqa: E402


def test_network_channel_is_registered():
    game_logging.setup_debug_logging()
    log = game_logging.get_debug_logger("network")
    # A registered channel maps to its real logger; an unregistered key falls
    # back to game.unknown.* (which is never configured / never emits).
    assert log.name == "game.network"
    assert "network" in game_logging._CHANNEL_TO_LOGGER
    assert "network" in game_logging._DEFAULT_CHANNELS


def test_network_channel_off_by_default():
    game_logging.setup_debug_logging()
    log = game_logging.get_debug_logger("network")
    # Default config has network disabled, so the per-frame diagnostic is a
    # no-op and singleplayer is unaffected.
    assert not log.isEnabledFor(logging.DEBUG)


class _FakeInput:
    def __init__(self, pressed):
        self._pressed = set(pressed)

    def is_key_just_pressed(self, key):
        return key in self._pressed


def _fake_game():
    return SimpleNamespace(in_start_menu=True, multiplayer_pending=False)


def test_start_menu_lists_multiplayer_entry():
    menu = StartMenu(_fake_game(), _FakeInput([]))
    assert "Multiplayer (dev)" in menu.options


def test_selecting_multiplayer_arms_the_bootstrap():
    game = _fake_game()
    menu = StartMenu(game, _FakeInput([pygame.K_RETURN]))
    menu.selected_option = menu.options.index("Multiplayer (dev)")
    menu.handle_events()
    assert game.multiplayer_pending is True
    assert game.in_start_menu is False


def test_selecting_start_game_does_not_arm_multiplayer():
    game = _fake_game()
    menu = StartMenu(game, _FakeInput([pygame.K_RETURN]))
    menu.selected_option = menu.options.index("Start Game")
    menu.handle_events()
    assert game.multiplayer_pending is False
    assert game.in_start_menu is False
