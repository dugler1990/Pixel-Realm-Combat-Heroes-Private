import pygame

_BG = (20, 18, 16)
_EDGE = (214, 178, 96)
_TEXT = (235, 228, 212)
_NAME = (240, 212, 138)
_DIM = (180, 170, 150)
_CHOICE = (40, 36, 28)
_CHOICE_ON = (70, 58, 36)


def wrap_text(font, text, width):
    words = (text or "").split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        trial = current + " " + word
        if font.size(trial)[0] <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class ConversationPanel:
    """Screen-space box for the active conversation. Input stays on the runner."""

    def __init__(self):
        self._name_font = None
        self._body_font = None
        self._cache = {}

    def draw(self, backend, snapshot, show_text=True):
        if not snapshot:
            return
        self._ensure_fonts()
        width, height = backend.get_size()
        panel_w = min(720, width - 48)
        text_w = panel_w - 36
        body = wrap_text(self._body_font, snapshot["visible"], text_w) if show_text else []
        if not show_text and snapshot["kind"] == "line":
            hint = "Space" if snapshot["revealed"] else "Space skips"
            body = [hint]
        choices = snapshot["choices"]
        name_h = self._name_font.get_linesize()
        line_h = self._body_font.get_linesize()
        choice_h = line_h + 8
        panel_h = 24 + name_h + 8 + max(1, len(body)) * line_h + 12 + len(choices) * choice_h + 16
        panel = pygame.Rect((width - panel_w) // 2, height - panel_h - 96, panel_w, panel_h)
        backend.draw_rect(_BG, panel)
        backend.draw_rect(_EDGE, panel, 2)

        x = panel.x + 18
        y = panel.y + 12
        name = snapshot["speaker"] or ""
        if name:
            name_surface = self._render(self._name_font, name, _NAME)
            backend.blit(name_surface, (x, y), cache_key=id(name_surface))
        y += name_h + 8
        for line in body:
            line_surface = self._render(self._body_font, line, _TEXT if show_text else _DIM)
            backend.blit(line_surface, (x, y), cache_key=id(line_surface))
            y += line_h
        y += 8
        for choice in choices:
            row = pygame.Rect(x - 8, y, text_w + 16, choice_h - 4)
            backend.draw_rect(_CHOICE_ON if choice["selected"] else _CHOICE, row)
            prefix = "> " if choice["selected"] else "  "
            choice_surface = self._render(self._body_font, prefix + choice["text"], _TEXT)
            backend.blit(choice_surface, (x, y + 2), cache_key=id(choice_surface))
            y += choice_h

    def _ensure_fonts(self):
        if self._name_font is None:
            self._name_font = pygame.font.Font(None, 28)
            self._body_font = pygame.font.Font(None, 24)

    def _render(self, font, text, color):
        key = (text, color, font.get_height())
        cached = self._cache.get(key)
        if cached is None:
            cached = font.render(text, True, color)
            self._cache[key] = cached
        return cached
