"""Tests for PlayerActionController dispatch and locking."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

pygame.init()

from abilities.dash import DashAbility  # noqa: E402
from abilities.held import HeldMagicAbility, HeldWeaponAbility  # noqa: E402
from abilities.player_controller import PlayerActionController  # noqa: E402
from Settings import evasion_data  # noqa: E402


def _make_controller():
    player = SimpleNamespace(
        current_evasion_index=0,
        status="down_idle",
        seated_object=None,
        attacking=False,
        inventory=SimpleNamespace(visible=False),
        has_belt=False,
        belt_capacity=0,
        _dash_runtime=None,
    )
    weapon = HeldWeaponAbility(lambda: None, None)
    magic = HeldMagicAbility(lambda *a, **k: None)
    evasion = {"slide": DashAbility("slide", evasion_data["slide"])}
    controller = PlayerActionController(
        player=player,
        weapon_ability=weapon,
        magic_ability=magic,
        evasion_abilities=evasion,
        evasion_order=["slide"],
        destroy_attack=lambda: None,
    )
    return controller, player


def test_suppresses_locomotion_false_while_attacking():
    controller, player = _make_controller()
    player.attacking = True
    assert controller.suppresses_locomotion(player) is False


def test_input_locked_during_dash():
    controller, player = _make_controller()
    player._dash_runtime = {"direction": "right", "end_time": 99999}
    assert controller.is_input_locked(player) is True
    assert controller.suppresses_locomotion(player) is True


def test_try_use_slot_evasion_starts_dash():
    controller, player = _make_controller()
    cost = evasion_data["slide"]["cost"]
    player.energy = cost + 10
    player.stats = {"speed": 10}
    player.rect = SimpleNamespace(center=(0, 0))
    player.hitbox = SimpleNamespace(x=0, y=0, center=(0, 0))
    player.groups = lambda: []
    player.direction = pygame.math.Vector2(1, 0)
    player.frame_index = 0
    player.attacking = False

    assert controller.try_use_slot(player, "evasion", direction="right") is True
    assert player._dash_runtime is not None
    assert player.energy == 10
