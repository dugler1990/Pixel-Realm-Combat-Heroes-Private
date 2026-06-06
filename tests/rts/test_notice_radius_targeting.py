import pygame
import pytest
from unittest.mock import MagicMock

from combat_unit import CombatUnit
from Interaction import InteractionResolver


@pytest.fixture(scope="module", autouse=True)
def _pygame_display():
    pygame.init()
    if not pygame.display.get_surface():
        pygame.display.set_mode((1, 1))


def _enemy_at(center, team_id="enemy_1"):
    enemy = MagicMock()
    enemy.team_id = team_id
    enemy.health = 10
    enemy.rect = pygame.Rect(0, 0, 20, 20)
    enemy.rect.center = center
    return enemy


def test_select_hostile_target_respects_notice_radius():
    resolver = InteractionResolver()
    near = _enemy_at((80, 0))
    far = _enemy_at((800, 0))

    visible = MagicMock()
    visible.sprites.return_value = [far, near]

    layout = MagicMock()
    layout.visible_sprites = visible
    level = MagicMock()
    level.layout_manager = layout
    level.interaction_resolver = resolver

    unit = MagicMock(spec=CombatUnit)
    unit.combat_context = {"level": level}
    unit.rect = pygame.Rect(0, 0, 20, 20)
    unit.rect.center = (0, 0)
    unit.id = 1
    unit.team_id = "neutral_passive"
    unit.combat_config = {"notice_radius": 100}
    unit.recent_attacker_team_id = None
    unit.recent_attacker_until_ms = 0
    unit._aggro_target_cache = None
    unit._aggro_cache_frame = -1
    unit._aggro_cache_prefer_team = None
    resolver.faction_policy.register_retaliation(unit, "enemy_1", 1000)
    unit.retaliate_team_id = "enemy_1"
    unit.retaliate_until_ms = 5000
    unit.get_target_distance_direction = CombatUnit.get_target_distance_direction.__get__(
        unit, CombatUnit
    )
    unit._is_valid_aggro_target = CombatUnit._is_valid_aggro_target.__get__(
        unit, CombatUnit
    )
    unit._notice_radius = CombatUnit._notice_radius.__get__(unit, CombatUnit)
    unit._current_prefer_team = CombatUnit._current_prefer_team.__get__(
        unit, CombatUnit
    )
    unit._aggro_cache_valid = CombatUnit._aggro_cache_valid.__get__(
        unit, CombatUnit
    )
    unit._pick_best_hostile = CombatUnit._pick_best_hostile.__get__(unit, CombatUnit)

    target = CombatUnit.select_hostile_target(unit)
    assert target is near
