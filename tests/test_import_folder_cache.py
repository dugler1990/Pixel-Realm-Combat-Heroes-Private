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
from Support import import_folder  # noqa: E402


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


@pytest.fixture
def frame_dir(tmp_path):
    folder = tmp_path / "anim"
    folder.mkdir()
    for name in ("2.png", "10.png", "1.png"):
        pygame.image.save(_make_frame((int(name[0]), 8)), str(folder / name))
    return folder


def test_import_folder_loads_each_file_once(frame_dir):
    load_calls = []

    def fake_load(path):
        name = os.path.basename(path)
        width = int(name.split(".")[0])
        load_calls.append(name)
        return _make_frame((width, 8))

    with mock.patch("pygame.image.load", side_effect=fake_load):
        first = import_folder(str(frame_dir))
        second = import_folder(str(frame_dir))

    assert len(load_calls) == 3
    assert load_calls == ["1.png", "2.png", "10.png"]
    assert first is second
    assert [surf.get_width() for surf in first] == [1, 2, 10]


def test_import_folder_scale_uses_separate_cache_entries(frame_dir):
    load_calls = []

    def fake_load(path):
        load_calls.append(path)
        return _make_frame((8, 8))

    with mock.patch("pygame.image.load", side_effect=fake_load):
        unscaled = import_folder(str(frame_dir))
        scaled = import_folder(str(frame_dir), scale=(4, 4))
        unscaled_again = import_folder(str(frame_dir))

    assert len(load_calls) == 3
    assert unscaled is unscaled_again
    assert unscaled is not scaled
    assert all(surf.get_size() == (8, 8) for surf in unscaled)
    assert all(surf.get_size() == (4, 4) for surf in scaled)
