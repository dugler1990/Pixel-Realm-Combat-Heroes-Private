"""Walk cycles advance on ground covered, not on the clock.

The contract is small enough to test on ``Entity.advance_frame`` directly, against a stub
carrying only the four attributes it reads. That keeps the test free of pygame display init
and of the whole level/quadtree apparatus, so it stays a statement about the rule rather than
about the machinery around it.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "Code"))


class _Walker:
    """Only what advance_frame touches."""

    def __init__(self, status, distance_moved, walk_statuses=frozenset({"move"})):
        self.status = status
        self.distance_moved = distance_moved
        self.animation_speed = 0.25
        self.WALK_STATUSES = walk_statuses


def _advance(status, distance, walk_statuses=frozenset({"move"})):
    from Entity import Entity

    return Entity.advance_frame(_Walker(status, distance, walk_statuses))


def test_walking_advances_in_proportion_to_distance():
    from Entity import PIXELS_PER_ANIM_FRAME

    assert _advance("move", PIXELS_PER_ANIM_FRAME) == pytest.approx(1.0)
    assert _advance("move", PIXELS_PER_ANIM_FRAME * 2) == pytest.approx(2.0)


def test_double_the_speed_is_double_the_frame_rate():
    """The property that makes sliding impossible: phase is a function of distance alone."""
    assert _advance("move", 12.0) == pytest.approx(2 * _advance("move", 6.0))


def test_blocked_walker_does_not_cycle():
    """Held against a wall the feet stop, because velocity is not what is measured."""
    assert _advance("move", 0.0) == 0.0


def test_idle_stays_on_the_clock():
    """Otherwise a standing entity would freeze mid-frame instead of breathing."""
    assert _advance("idle", 0.0) == 0.25
    assert _advance("attack", 0.0) == 0.25


def test_each_class_declares_its_own_walk_vocabulary():
    """The four status vocabularies really differ, so this is not a formality."""
    from Player import BasePlayer
    from Enemy import Enemy
    from friendly import Friendly
    from combat_unit import CombatUnit
    from NeutralCharacter import NeutralCharacter

    assert BasePlayer.WALK_STATUSES == {"up", "down", "left", "right"}
    assert Enemy.WALK_STATUSES == {"move"}
    assert Friendly.WALK_STATUSES == {"move"}
    assert CombatUnit.WALK_STATUSES == {"move"}
    assert NeutralCharacter.WALK_STATUSES == {"walking"}


def test_player_idle_and_attack_are_not_walk_statuses():
    """The player suffixes rather than replaces, so "down_idle" must not match "down"."""
    from Player import BasePlayer

    for status in ("down_idle", "down_attack", "sit_idle", "jump_down", "land_down"):
        assert status not in BasePlayer.WALK_STATUSES


def test_barb_cadence_is_a_plausible_walking_pace():
    """Guards the constant itself: 19 frames at speed 6 on a 30fps tick.

    Locks in roughly one cycle per second. If PIXELS_PER_ANIM_FRAME is ever retuned far
    from that, this fails and says so in cadence rather than in arbitrary units.
    """
    from Entity import PIXELS_PER_ANIM_FRAME

    frames_per_cycle, speed_px_per_tick, fps = 19, 6, 30
    cycles_per_second = (speed_px_per_tick * fps) / (PIXELS_PER_ANIM_FRAME * frames_per_cycle)
    assert 0.6 < cycles_per_second < 1.6, f"{cycles_per_second:.2f} cycles/sec is not a walk"
