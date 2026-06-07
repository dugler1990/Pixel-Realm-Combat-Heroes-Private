import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from render_backend import CPUBackend
from YsortCameraGroup import YSortCameraGroup


class FakeGrassManager:
    def update_render(self, *args, **kwargs):
        return {}

    def apply_force(self, *args, **kwargs):
        return None


class FakeSprite(pygame.sprite.Sprite):
    def __init__(self, center, color=(255, 0, 0), size=(20, 20)):
        super().__init__()
        self.image = pygame.Surface(size, pygame.SRCALPHA)
        self.image.fill(color)
        self.rect = self.image.get_rect(center=center)


class Focus:
    def __init__(self, center):
        self.rect = pygame.Rect(0, 0, 1, 1)
        self.rect.center = center


def make_camera_group(player, obj):
    pygame.display.init()
    pygame.display.set_mode((200, 200))
    ground = pygame.sprite.Group(FakeSprite((100, 100), color=(0, 40, 0), size=(400, 400)))
    backend = CPUBackend(pygame.display.get_surface())
    group = YSortCameraGroup(ground, FakeGrassManager(), [], backend=backend)
    group.add(obj)
    group.add(player)
    return group


def test_custom_draw_with_no_camera_focus_keeps_player_centered_objects_visible():
    player = FakeSprite((100, 100), color=(0, 0, 255))
    obj = FakeSprite((100, 100), color=(255, 0, 0))
    group = make_camera_group(player, obj)
    surface = pygame.display.get_surface()

    surface.fill((0, 0, 0))
    group.custom_draw(player, 0.016, 0, 0.5)

    assert surface.get_at((100, 100))[:3] in ((255, 0, 0), (0, 0, 255))
    assert group.offset == pygame.math.Vector2(0, 0)


def test_custom_draw_with_far_camera_focus_moves_player_centered_objects_offscreen():
    player = FakeSprite((100, 100), color=(0, 0, 255))
    obj = FakeSprite((100, 100), color=(255, 0, 0))
    group = make_camera_group(player, obj)
    surface = pygame.display.get_surface()
    far_focus = Focus((1000, 1000))

    surface.fill((0, 0, 0))
    group.custom_draw(player, 0.016, 0, 0.5, camera_focus=far_focus)

    assert surface.get_at((100, 100))[:3] == (0, 0, 0)
    assert group.offset == pygame.math.Vector2(900, 900)


def test_custom_draw_with_camera_focus_on_object_keeps_object_visible():
    player = FakeSprite((300, 300), color=(0, 0, 255))
    obj = FakeSprite((120, 120), color=(255, 0, 0))
    group = make_camera_group(player, obj)
    surface = pygame.display.get_surface()
    focus = Focus(obj.rect.center)

    surface.fill((0, 0, 0))
    group.custom_draw(player, 0.016, 0, 0.5, camera_focus=focus)

    assert surface.get_at((100, 100))[:3] == (255, 0, 0)
    assert group.offset == pygame.math.Vector2(20, 20)
