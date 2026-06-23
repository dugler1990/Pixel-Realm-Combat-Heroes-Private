import pygame
import pytest

from combat_unit import CombatUnit


@pytest.fixture(scope="module", autouse=True)
def _pygame_display():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))


class _ResumeStub:
    """Minimal object for resume_default / combat_update without full sprite init."""

    def __init__(self):
        self.status = "attack"
        self.direction = pygame.math.Vector2(3, 4)
        self.frozen = False


def test_combat_unit_resume_default_sets_idle():
    unit = _ResumeStub()
    CombatUnit.resume_default(unit)
    assert unit.status == "idle"
    assert unit.direction == pygame.math.Vector2(0, 0)


def test_combat_update_calls_resume_default_when_no_target():
    unit = _ResumeStub()
    unit.select_hostile_target = lambda **kwargs: None
    unit.resume_default = lambda: CombatUnit.resume_default(unit)
    CombatUnit.combat_update(unit, None)
    assert unit.status == "idle"
    assert unit.direction == pygame.math.Vector2(0, 0)
