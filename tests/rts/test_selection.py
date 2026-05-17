import pygame

from rts.selection import SelectableRegistry

from fakes import FakeSprite


def test_registry_filters_supported_selectable_types():
    seat = FakeSprite(center=(0, 0), kind="seat")
    building = FakeSprite(center=(10, 0), kind="rts_building")
    unit = FakeSprite(center=(20, 0), kind="rts_unit")
    resource = FakeSprite(center=(30, 0), kind="resource_node")
    explicit = FakeSprite(center=(40, 0), rts_selectable=True)
    ignored = FakeSprite(center=(50, 0), kind="tree")

    registry = SelectableRegistry()
    registry.rebuild([seat, building, unit, resource, explicit, ignored])

    assert [item.sprite for item in registry.selectables] == [
        seat,
        building,
        unit,
        resource,
        explicit,
    ]


def test_select_bottom_left_uses_largest_y_then_smallest_x():
    left_bottom = FakeSprite(center=(10, 100), kind="seat")
    right_bottom = FakeSprite(center=(50, 100), kind="seat")
    higher_left = FakeSprite(center=(0, 40), kind="seat")
    registry = SelectableRegistry()
    registry.rebuild([right_bottom, higher_left, left_bottom])

    selected = registry.select_bottom_left()

    assert selected.sprite is left_bottom


def test_select_bottom_left_prefers_visible_candidates():
    offscreen_lower = FakeSprite(center=(10, 300), kind="seat")
    visible = FakeSprite(center=(100, 100), kind="seat")
    camera_rect = pygame.Rect(50, 50, 200, 200)
    registry = SelectableRegistry()
    registry.rebuild([offscreen_lower, visible])

    selected = registry.select_bottom_left(camera_rect)

    assert selected.sprite is visible


def test_directional_navigation_chooses_nearest_candidate_in_direction():
    origin = FakeSprite(center=(100, 100), kind="seat")
    nearest_right = FakeSprite(center=(150, 100), kind="seat")
    farther_right = FakeSprite(center=(240, 100), kind="seat")
    left = FakeSprite(center=(30, 100), kind="seat")
    registry = SelectableRegistry()
    registry.rebuild([origin, farther_right, left, nearest_right])
    registry.selected = registry.selectables[0]

    selected = registry.move_selection(pygame.math.Vector2(1, 0))

    assert selected.sprite is nearest_right


def test_directional_navigation_uses_bottom_left_when_nothing_selected():
    lower = FakeSprite(center=(20, 150), kind="seat")
    higher = FakeSprite(center=(10, 20), kind="seat")
    registry = SelectableRegistry()
    registry.rebuild([higher, lower])

    selected = registry.move_selection(pygame.math.Vector2(1, 0))

    assert selected.sprite is lower


def test_selected_sprite_is_preserved_across_rebuild():
    first = FakeSprite(center=(0, 0), kind="seat")
    second = FakeSprite(center=(50, 0), kind="seat")
    registry = SelectableRegistry()
    registry.rebuild([first, second])
    registry.selected = registry.selectables[1]

    registry.rebuild([first, second])

    assert registry.selected is not None
    assert registry.selected.sprite is second
