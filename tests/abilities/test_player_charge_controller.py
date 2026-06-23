"""Tests for hold/release charge controller wiring."""

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


@pytest.fixture(autouse=True)
def _ensure_display():
    if not pygame.display.get_surface():
        pygame.display.set_mode((64, 64))
    yield


from abilities.leap_slam import ChargedLeapSlamAbility  # noqa: E402
from abilities.player_controller import PlayerActionController  # noqa: E402
from abilities.protocol import PlayerAbilityContext  # noqa: E402
from Settings import ability_data  # noqa: E402


class _InputManager:
    def __init__(self):
        self.previous_key_states = {}
        self.pressed = set()
        self.just_pressed = set()

    def is_key_pressed(self, key):
        return key in self.pressed

    def is_key_just_pressed(self, key):
        return key in self.just_pressed


def _make_leap_controller(energy=30):
    player = SimpleNamespace(
        current_evasion_index=0,
        status="right_idle",
        seated_object=None,
        attacking=False,
        inventory=SimpleNamespace(visible=False),
        has_belt=False,
        belt_capacity=0,
        _dash_runtime=None,
        _charge_runtime=None,
        _leap_runtime=None,
        energy=energy,
        rect=SimpleNamespace(center=(0, 0)),
        hitbox=SimpleNamespace(x=0, y=0, center=(0, 0)),
        direction=pygame.math.Vector2(1, 0),
        frame_index=0,
        groups=lambda: [],
        get_direction_as_string=lambda: "right",
        last_i_press_time=0,
        last_q_press_time=0,
        last_p_press_time=0,
        can_switch_weapon=True,
        can_switch_magic=True,
        can_switch_evasion=True,
        weapon_index=0,
        magic_index=0,
        weapon="sword",
        magic="flame",
        level=SimpleNamespace(
            toggle_inventory=lambda: None,
            toggle_attack_selection=lambda: None,
            toggle_menu=lambda: None,
        ),
    )
    leap = ChargedLeapSlamAbility("leap_slam", dict(ability_data["leap_slam"]))
    controller = PlayerActionController(
        player=player,
        weapon_ability=SimpleNamespace(try_start=lambda *a, **k: False),
        magic_ability=SimpleNamespace(try_start=lambda *a, **k: False),
        evasion_abilities={"leap_slam": leap},
        evasion_order=["leap_slam"],
        destroy_attack=lambda: None,
    )
    return controller, player, leap


def test_press_and_release_launches_leap():
    controller, player, leap = _make_leap_controller()
    ctx = PlayerAbilityContext(animation_player=None, create_trap=lambda *a, **k: None)
    assert leap.on_press(player, ctx, direction="right") is True
    assert player._charge_runtime is not None
    assert leap.on_release(player, ctx, direction="right") is True
    assert player._leap_runtime is not None
    assert player._charge_runtime is None


def test_input_locked_during_charge_and_airborne():
    controller, player, leap = _make_leap_controller()
    assert controller.is_input_locked(player) is False
    assert controller.is_movement_locked(player) is False
    player._charge_runtime = {"start_time": 0, "direction": "right", "_ability": leap}
    assert controller.is_input_locked(player) is True
    assert controller.is_movement_locked(player) is False
    player._charge_runtime = None
    player._leap_runtime = {"phase": "airborne", "_ability": leap}
    assert controller.is_input_locked(player) is True
    assert controller.is_movement_locked(player) is False


def test_charge_direction_updates_while_holding():
    controller, player, leap = _make_leap_controller()
    ctx = PlayerAbilityContext(animation_player=None, create_trap=lambda *a, **k: None)
    player.get_direction_as_string = lambda: "left"
    leap.on_press(player, ctx, direction="right")
    leap._tick_charge(player, player._charge_runtime, ctx)
    assert player._charge_runtime["direction"] == "left"


def test_charge_suppresses_locomotion_only_in_air():
    leap = ChargedLeapSlamAbility("leap_slam", dict(ability_data["leap_slam"]))
    player = SimpleNamespace(_charge_runtime={"direction": "right"}, _leap_runtime=None, _dash_runtime=None)
    assert leap.suppresses_locomotion(player) is False
    player._leap_runtime = {"phase": "airborne"}
    assert leap.suppresses_locomotion(player) is True


def test_evasion_toggle_cycles_loadout():
    controller, player, leap = _make_leap_controller()
    from abilities.dash import DashAbility

    slide = DashAbility("slide", dict(ability_data["slide"]))
    controller.evasion_abilities = {"slide": slide, "leap_slam": leap}
    controller.evasion_order = ["slide", "leap_slam"]
    player.current_evasion_index = 0
    inputs = _InputManager()
    inputs.just_pressed.add(pygame.K_r)
    controller.handle_input(player, inputs)
    assert player.current_evasion_index == 1


def test_energy_not_spent_on_press_via_controller():
    controller, player, leap = _make_leap_controller(energy=20)
    cost = ability_data["leap_slam"]["cost"]
    inputs = _InputManager()
    inputs.just_pressed.add(pygame.K_c)
    controller.handle_input(player, inputs)
    assert player._charge_runtime is not None
    assert player.energy == 20
