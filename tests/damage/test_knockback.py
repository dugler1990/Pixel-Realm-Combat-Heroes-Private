"""Knockback by mass: Entity.knockback_scale and apply_impulse (damage chunk 1).

A shove moves a body REFERENCE_MASS / (mass + gear_weight) as far as the force says, inside the
scale limits, then cut by strength. The barb (mass REFERENCE_MASS, no strength) moves exactly the
force, as before this chunk.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

CODE_DIR = Path(__file__).resolve().parents[2] / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import pygame  # noqa: E402

from Entity import Entity, knockback_scale  # noqa: E402
from Settings import (  # noqa: E402
    KNOCKBACK_SCALE_MAX,
    KNOCKBACK_SCALE_MIN,
    REFERENCE_MASS,
    STRENGTH_KNOCKBACK_CUT,
    STRENGTH_KNOCKBACK_FLOOR,
    monster_data,
)


class _Body:
    """What apply_impulse reads and writes: a hitbox, a velocity, mass, gear, maybe stats."""

    def __init__(self, mass=None, gear_weight=None, stats=None):
        if mass is not None:
            self.mass = mass
        if gear_weight is not None:
            self.gear_weight = gear_weight
        if stats is not None:
            self.stats = stats
        self.hitbox = pygame.Rect(0, 0, 10, 10)
        self.velocity = pygame.math.Vector2(0, 0)
        self._dash_runtime = None
        self._leap_runtime = None

    def cancel_displacement_abilities(self):
        Entity.cancel_displacement_abilities(self)

    def plant_sprite_on_hitbox(self):
        pass

    def shove(self, x, y=0.0, follow_through=0.5):
        Entity.apply_impulse(self, pygame.math.Vector2(x, y), follow_through=follow_through)


def test_reference_body_moves_exactly_the_force():
    body = _Body(mass=REFERENCE_MASS)
    body.shove(40, -12)
    assert (body.hitbox.x, body.hitbox.y) == (40, -12)
    assert body.velocity == pygame.math.Vector2(20, -6)


def test_body_without_mass_counts_as_reference():
    assert knockback_scale(SimpleNamespace()) == 1.0


def test_four_times_the_mass_moves_a_quarter():
    body = _Body(mass=4 * REFERENCE_MASS)
    body.shove(40)
    assert body.hitbox.x == 10
    assert body.velocity.x == pytest.approx(5.0)


def test_gear_weight_counts_as_mass():
    plated = _Body(mass=REFERENCE_MASS / 2, gear_weight=REFERENCE_MASS / 2)
    assert knockback_scale(plated) == pytest.approx(1.0)
    assert knockback_scale(_Body(mass=REFERENCE_MASS / 2)) == pytest.approx(2.0)


def test_scale_stays_inside_its_limits():
    assert knockback_scale(_Body(mass=1)) == KNOCKBACK_SCALE_MAX
    assert knockback_scale(_Body(mass=1e6)) == KNOCKBACK_SCALE_MIN
    assert knockback_scale(_Body(mass=0)) == KNOCKBACK_SCALE_MAX


def test_strength_cuts_the_shove():
    strength = 10
    expected = 1.0 - STRENGTH_KNOCKBACK_CUT * strength
    assert knockback_scale(_Body(stats={"strength": strength})) == pytest.approx(expected)
    attr_body = SimpleNamespace(strength=strength)
    assert knockback_scale(attr_body) == pytest.approx(expected)


def test_strength_cut_has_a_floor():
    assert knockback_scale(_Body(stats={"strength": 1000})) == pytest.approx(STRENGTH_KNOCKBACK_FLOOR)


def test_no_strength_no_cut():
    assert knockback_scale(_Body(stats={"health": 100})) == 1.0


@pytest.mark.parametrize("name", sorted(monster_data))
def test_every_monster_has_a_mass_and_no_resistance(name):
    entry = monster_data[name]
    assert "resistance" not in entry
    assert isinstance(entry.get("mass"), (int, float)) and entry["mass"] > 0
