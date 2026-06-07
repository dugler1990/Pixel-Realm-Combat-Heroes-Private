import os
import sys
from pathlib import Path
from unittest import mock

import pygame
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from ImageCache import ImageCache  # noqa: E402


@pytest.fixture(autouse=True)
def pygame_headless():
    pygame.init()
    pygame.display.set_mode((1, 1))
    yield


@pytest.fixture(autouse=True)
def clear_image_caches():
    ImageCache.cache.clear()
    ImageCache._folder_cache.clear()
    ImageCache._scaled_cache.clear()
    yield
    ImageCache.cache.clear()
    ImageCache._folder_cache.clear()
    ImageCache._scaled_cache.clear()


def _make_frame(size):
    surf = pygame.Surface(size, pygame.SRCALPHA)
    surf.fill((255, 0, 0, 255))
    return surf


def test_load_scaled_hits_disk_once(tmp_path):
    img_path = tmp_path / "icon.png"
    pygame.image.save(_make_frame((32, 32)), str(img_path))
    load_calls = []

    def counting_load(path):
        load_calls.append(path)
        return _make_frame((32, 32))

    with mock.patch("pygame.image.load", side_effect=counting_load):
        first = ImageCache.load_scaled(str(img_path), (16, 16))
        second = ImageCache.load_scaled(str(img_path), (16, 16))

    assert first is second
    assert len(load_calls) == 1


def test_load_scaled_different_sizes_are_distinct(tmp_path):
    img_path = tmp_path / "icon.png"
    pygame.image.save(_make_frame((32, 32)), str(img_path))
    load_calls = []

    def counting_load(path):
        load_calls.append(path)
        return _make_frame((32, 32))

    with mock.patch("pygame.image.load", side_effect=counting_load):
        small = ImageCache.load_scaled(str(img_path), (16, 16))
        large = ImageCache.load_scaled(str(img_path), (24, 24))

    assert small is not large
    assert len(load_calls) == 1
