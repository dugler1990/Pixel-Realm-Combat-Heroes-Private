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

import render_backend  # noqa: E402
from render_backend import CPUBackend, GPUBackend, create_backend  # noqa: E402


@pytest.fixture(autouse=True)
def pygame_headless():
    pygame.init()
    yield


def _gl_context_available():
    try:
        pygame.display.set_mode((64, 64), pygame.OPENGL | pygame.DOUBLEBUF)
        return True
    except pygame.error:
        return False
    finally:
        pygame.display.quit()
        pygame.display.init()


# Module-level probe: the dummy SDL driver (forced above for headless CI) cannot
# create an OpenGL context, so GPU-path tests skip cleanly there while still
# running on a real display driver (e.g. the dev machine).
pygame.init()
requires_gl = pytest.mark.skipif(
    not _gl_context_available(), reason="no OpenGL-capable display driver"
)


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


def test_render_backend_draw_rect_pixel_parity():
    """Regression guard: draw_rect's offscreen-surface+blit must be pixel-identical
    to a direct pygame.draw.rect for opaque colors (the claim the shared helpers
    in RenderBackend.draw_rect/draw_circle/compose rely on)."""
    backend = create_backend(64, 64)
    backend.fill((0, 0, 0))
    backend.draw_rect((0, 0, 255), pygame.Rect(10, 10, 8, 8))
    backend.draw_rect((255, 0, 0), pygame.Rect(30, 10, 12, 12), 2)

    direct = pygame.Surface((64, 64))
    direct.fill((0, 0, 0))
    pygame.draw.rect(direct, (0, 0, 255), pygame.Rect(10, 10, 8, 8))
    pygame.draw.rect(direct, (255, 0, 0), pygame.Rect(30, 10, 12, 12), 2)

    for x in range(64):
        for y in range(64):
            assert backend.raw_surface.get_at((x, y)) == direct.get_at((x, y))


@requires_gl
def test_create_backend_returns_gpu_backend(monkeypatch):
    monkeypatch.setattr(render_backend, "RENDER_BACKEND", "gpu")
    backend = create_backend(64, 64)
    assert isinstance(backend, GPUBackend)
    assert backend.raw_surface is None
    assert backend.get_size() == (64, 64)


@requires_gl
def test_gpu_backend_blit_smoke(monkeypatch):
    import numpy as np
    from OpenGL.GL import GL_BACK, GL_RGBA, GL_UNSIGNED_BYTE, glReadBuffer, glReadPixels

    monkeypatch.setattr(render_backend, "RENDER_BACKEND", "gpu")
    backend = create_backend(64, 64)
    backend.begin_frame((0, 0, 0))
    src = pygame.Surface((8, 8))
    src.fill((255, 0, 0))
    backend.blit(src, (10, 10))
    backend.fill((0, 255, 0), pygame.Rect(30, 30, 8, 8))

    glReadBuffer(GL_BACK)
    raw = glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE)
    # glReadPixels rows are bottom-up; flip to match top-left-origin pygame coords.
    arr = np.flipud(np.frombuffer(raw, dtype=np.uint8).reshape(64, 64, 4))
    assert tuple(arr[14, 14, :3]) == (255, 0, 0)
    assert tuple(arr[34, 34, :3]) == (0, 255, 0)
