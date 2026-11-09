import pygame

_BG = (16, 14, 12)
_EDGE = (214, 178, 96)
_TEXT = (235, 228, 212)


class SpeechBubble:
    def __init__(self, text, world_x, world_y, until_ms, speaker_name):
        self.text = text
        self.world_x = world_x
        self.world_y = world_y
        self.until_ms = until_ms
        self.speaker_name = speaker_name


class SpeechBubblePool:
    """A fixed handful of world-space lines. Off-screen ones are not drawn."""

    MAX = 6

    def __init__(self, lifetime_ms=3200):
        self.lifetime_ms = lifetime_ms
        self.items = []
        self._font = None
        self._cache = {}

    def spawn(self, event, world_pos, now_ms):
        if len(self.items) >= self.MAX:
            self.items.pop(0)
        self.items.append(
            SpeechBubble(
                event.text,
                world_pos[0],
                world_pos[1],
                now_ms + self.lifetime_ms,
                event.speaker_name,
            )
        )

    def tick(self, now_ms):
        self.items = [item for item in self.items if item.until_ms > now_ms]

    def draw(self, backend, offset, enabled=True):
        if not enabled or not self.items:
            return
        font = self._get_font()
        width, height = backend.get_size()
        for item in self.items:
            sx = int(item.world_x - offset.x)
            sy = int(item.world_y - offset.y)
            if sx < -80 or sy < -80 or sx > width + 80 or sy > height + 80:
                continue
            surface = self._surface(font, item.text)
            rect = surface.get_rect(midbottom=(sx, sy))
            box = rect.inflate(12, 8)
            backend.draw_rect(_BG, box)
            backend.draw_rect(_EDGE, box, 1)
            backend.blit(surface, rect, cache_key=id(surface))

    def label(self, text):
        return self._surface(self._get_font(), text)

    def _get_font(self):
        if self._font is None:
            self._font = pygame.font.Font(None, 22)
        return self._font

    def _surface(self, font, text):
        cached = self._cache.get(text)
        if cached is None:
            cached = font.render(text, True, _TEXT)
            self._cache[text] = cached
        return cached
