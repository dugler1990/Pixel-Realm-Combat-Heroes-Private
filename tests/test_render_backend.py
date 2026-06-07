import os
import sys
from pathlib import Path

import pygame
import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = REPO_ROOT / "Code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from render_backend import CPUBackend, create_backend  # noqa: E402


@pytest.fixture(autouse=True)
def pygame_headless():
    pygame.init()
    yield


def test_create_backend_returns_cpu_backend():
    backend = create_backend(320, 240)
    assert isinstance(backend, CPUBackend)
    assert isinstance(backend.raw_surface, pygame.Surface)
    assert backend.get_size() == (320, 240)


def test_cpu_backend_blit_fill_present_smoke():
    backend = create_backend(64, 64)
    src = pygame.Surface((8, 8))
    src.fill((255, 0, 0))
    backend.fill((0, 0, 0))
    backend.blit(src, (10, 10))
    backend.present()
    assert backend.raw_surface.get_at((10, 10))[:3] == (255, 0, 0)
