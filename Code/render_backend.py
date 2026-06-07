import pygame

from Settings import DISPLAY_FLAGS, RENDER_BACKEND


class RenderBackend:
    def get_size(self) -> tuple[int, int]:
        raise NotImplementedError

    def begin_frame(self, clear_color=(0, 0, 0)):
        raise NotImplementedError

    def blit(self, surface, dest, *, flags=0, area=None):
        raise NotImplementedError

    def fill(self, color, rect=None):
        raise NotImplementedError

    def present(self):
        raise NotImplementedError

    @property
    def raw_surface(self) -> pygame.Surface | None:
        raise NotImplementedError


class CPUBackend(RenderBackend):
    def __init__(self, surface: pygame.Surface):
        self._surface = surface

    def get_size(self) -> tuple[int, int]:
        return self._surface.get_size()

    def begin_frame(self, clear_color=(0, 0, 0)):
        self._surface.fill(clear_color)

    def blit(self, surface, dest, *, flags=0, area=None):
        if area is not None:
            self._surface.blit(surface, dest, area=area, special_flags=flags)
        else:
            self._surface.blit(surface, dest, special_flags=flags)

    def fill(self, color, rect=None):
        if rect is not None:
            self._surface.fill(color, rect)
        else:
            self._surface.fill(color)

    def present(self):
        pygame.display.update()

    @property
    def raw_surface(self) -> pygame.Surface:
        return self._surface


def create_backend(width: int, height: int) -> RenderBackend:
    if RENDER_BACKEND == "cpu":
        surface = pygame.display.set_mode((width, height), DISPLAY_FLAGS)
        return CPUBackend(surface)
    raise NotImplementedError("gpu backend is Phase 1")
