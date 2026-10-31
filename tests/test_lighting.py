"""Lighting: darkness by the hour, darkness inside a building, and what burns in it."""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Code"))

import Lighting as lighting_mod  # noqa: E402
from Lighting import LightingManager, LightSource  # noqa: E402


class LightRecorder:
    """Records the light pass instead of drawing it."""

    def __init__(self):
        self.ambient = None
        self.lights = []

    def begin_light_pass(self, ambient):
        self.ambient = ambient

    def draw_light(self, center, radius, color):
        self.lights.append((center, radius))

    def end_light_pass(self):
        pass

    def composite_lights(self):
        pass


def _inside(name):
    return SimpleNamespace(name=name)


def _render(manager, hour, inside=None, torches=(), player_center=(100, 100)):
    backend = LightRecorder()
    manager.render(backend, hour, (0, 0), (200, 200), torches=torches,
                   player_center=player_center, inside=inside)
    return backend


def test_noon_outside_skips_the_light_pass():
    backend = _render(LightingManager(), 14)
    assert backend.ambient is None and backend.lights == []


def test_night_outside_is_the_night_darkness_and_your_light():
    manager = LightingManager()
    backend = _render(manager, 2)
    assert backend.ambient == manager.MIN_AMBIENT
    assert backend.lights == [((100, 100), manager.player_radius_dark)]


def test_inside_it_is_dark_at_noon_and_your_light_is_a_torch():
    manager = LightingManager()
    backend = _render(manager, 14, inside=_inside("great_pyramid"))
    assert backend.ambient == lighting_mod.INTERIOR_AMBIENT
    assert backend.lights == [((100, 100), manager.player_radius_dark)]


def test_a_torch_burns_where_it_stands():
    manager = LightingManager()
    torch = SimpleNamespace(rect=pygame.Rect(40, 50, 20, 30))
    backend = _render(manager, 2, torches=[torch], player_center=None)
    assert backend.lights == [((50, 65), manager.torch_radius)]


def test_a_brazier_burns_like_a_torch_for_its_building():
    manager = LightingManager()
    light = manager.add_prop_light({"type": "brazier", "building": "great_pyramid"},
                                   pygame.Rect(100, 200, 30, 40))
    assert (light.x, light.y, light.building) == (115, 220, "great_pyramid")
    assert (light.radius, light.color, light.flicker) == (
        manager.torch_radius, manager.torch_color, manager.torch_flicker)
    statue = manager.add_prop_light({"type": "statue", "building": "great_pyramid"},
                                    pygame.Rect(0, 0, 10, 10))
    assert statue is None


def test_a_brazier_shines_only_from_inside_its_building():
    manager = LightingManager()
    manager.add_prop_light({"type": "brazier", "building": "great_pyramid"},
                           pygame.Rect(90, 90, 20, 20))

    def lights(hour, inside):
        return _render(manager, hour, inside=inside, player_center=None).lights

    assert lights(14, _inside("great_pyramid")) == [((100, 100), manager.torch_radius)]
    assert lights(14, _inside("a_house")) == [], "another building's"
    assert lights(2, None) == [], "at night outside the roof covers it"


def test_a_light_outdoors_shines_outside_and_in():
    manager = LightingManager()
    manager.add_light(LightSource(x=100, y=100))
    assert len(_render(manager, 2, player_center=None).lights) == 1
    assert len(_render(manager, 14, inside=_inside("great_pyramid"), player_center=None).lights) == 1
