import pygame
import pytest
from unittest.mock import MagicMock, patch

from combat_unit import CombatUnit
from rts.entities import RtsWorker
from rts.entities.gather_states import GATHERING


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
    unit.select_hostile_target = lambda: None
    unit.resume_default = lambda: CombatUnit.resume_default(unit)
    CombatUnit.combat_update(unit, None)
    assert unit.status == "idle"
    assert unit.direction == pygame.math.Vector2(0, 0)


def test_tribe_resume_default_preserves_gather_status():
    worker = RtsWorker((100, 100), [], "eskimo", "worker_eskimo")
    worker.status = "gather"
    worker.gather_state = GATHERING
    worker.resume_default()
    assert worker.status == "gather"
    assert worker.gather_state == GATHERING


def test_tribe_resume_default_preserves_roam_status():
    worker = RtsWorker((100, 100), [], "eskimo", "worker_eskimo")
    worker.behavior = "roam"
    worker.status = "move"
    worker.direction = pygame.math.Vector2(1, 0)
    worker.resume_default()
    assert worker.status == "move"
    assert worker.direction == pygame.math.Vector2(1, 0)


def test_tribe_update_skips_driver_steer_when_combat_target():
    worker = RtsWorker((100, 100), [], "eskimo", "worker_eskimo")
    mock_target = MagicMock()
    mock_driver = MagicMock()

    with patch.object(worker, "select_hostile_target", return_value=mock_target):
        with patch("rts.entities.tribe_member.pick_driver", return_value=mock_driver):
            worker.update()
            mock_driver.steer.assert_not_called()

    with patch.object(worker, "select_hostile_target", return_value=None):
        with patch("rts.entities.tribe_member.pick_driver", return_value=mock_driver):
            worker.update()
            mock_driver.steer.assert_called_once()


def test_worker_combat_update_with_target_no_distance_error():
    worker = RtsWorker((100, 100), [], "eskimo", "worker_eskimo")
    assert worker.team_id == "eskimo_village"
    mock_target = MagicMock()
    mock_target.rect = pygame.Rect(120, 100, 20, 20)
    worker.combat_strategy = MagicMock()
    with patch.object(worker, "select_hostile_target", return_value=mock_target):
        worker.combat_update(None, None)
    worker.combat_strategy.decide_action.assert_called_once()
