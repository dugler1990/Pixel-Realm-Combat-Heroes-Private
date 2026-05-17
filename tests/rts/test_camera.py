import math

import pygame

from rts.camera import RtsCamera

from fakes import FakeSprite


def test_snap_to_sprite_and_raw_position():
    camera = RtsCamera()
    sprite = FakeSprite(center=(125, 250))

    camera.snap_to(sprite)

    assert camera.rect.center == (125, 250)
    assert camera.pos == pygame.math.Vector2(125, 250)

    camera.snap_to((400, 300))

    assert camera.rect.center == (400, 300)
    assert camera.pos == pygame.math.Vector2(400, 300)


def test_move_normalizes_diagonal_direction():
    camera = RtsCamera(pos=(100, 100), speed=100)

    camera.move(pygame.math.Vector2(1, 1), 1.0)

    expected_delta = 100 / math.sqrt(2)
    assert camera.pos.x == pytest_approx(100 + expected_delta)
    assert camera.pos.y == pytest_approx(100 + expected_delta)


def test_clamp_keeps_camera_inside_bounds():
    camera = RtsCamera(pos=(50, 50), speed=1000)
    bounds = pygame.Rect(0, 0, 200, 200)

    camera.move(pygame.math.Vector2(-1, -1), 1.0, bounds)

    assert camera.pos.x == 0
    assert camera.pos.y == 0
    assert camera.rect.center == (0, 0)

    camera.move(pygame.math.Vector2(1, 1), 1.0, bounds)

    assert camera.pos.x == 200
    assert camera.pos.y == 200
    assert camera.rect.center == (200, 200)


def test_zero_direction_does_not_move_camera():
    camera = RtsCamera(pos=(75, 90), speed=100)

    camera.move(pygame.math.Vector2(0, 0), 1.0)

    assert camera.pos == pygame.math.Vector2(75, 90)
    assert camera.rect.center == (75, 90)


def pytest_approx(value):
    import pytest

    return pytest.approx(value)
