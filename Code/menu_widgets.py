"""Keyboard-first menu widgets for the online screens, drawn with plain rects and text.

A Form holds widgets top to bottom. Up/Down (or Tab / Shift+Tab) moves focus, Left/Right
changes a Choice, Enter presses a Button or picks a ListView row, typing goes to the
focused TextField. No mouse and no art yet: the preview's look comes in a later pass.
"""

import pygame

TEXT = (235, 228, 212)
DIM = (140, 134, 122)
ACCENT = (214, 178, 96)
ERROR = (232, 96, 84)
BOX = (34, 31, 28)
BOX_FOCUS = (66, 56, 40)
BORDER = (90, 82, 70)
BACKGROUND = (12, 10, 9)

ROW_H = 44
_fonts = {}


def font(size):
    f = _fonts.get(size)
    if f is None:
        f = _fonts[size] = pygame.font.Font(None, size)
    return f


def draw_text(surface, text, pos, size=28, color=TEXT, anchor="topleft"):
    image = font(size).render(text, True, color)
    rect = image.get_rect(**{anchor: pos})
    surface.blit(image, rect)
    return rect


def fit(text, size, width):
    """Cut text so it renders within `width` pixels."""
    f = font(size)
    if f.size(text)[0] <= width:
        return text
    while text and f.size(text + "...")[0] > width:
        text = text[:-1]
    return text + "..."


def _box(surface, rect, focused):
    pygame.draw.rect(surface, BOX_FOCUS if focused else BOX, rect)
    pygame.draw.rect(surface, ACCENT if focused else BORDER, rect, 2)


class Widget:
    focusable = True

    def __init__(self):
        self.visible = True

    def height(self):
        return ROW_H

    def handle(self, event):
        """An action string, or None."""
        return None

    def draw(self, surface, rect, focused):
        raise NotImplementedError


class Label(Widget):
    focusable = False

    def __init__(self, text="", color=DIM, size=26):
        super().__init__()
        self.text = text
        self.color = color
        self.size = size

    def height(self):
        return 30 if self.text else 0

    def draw(self, surface, rect, focused):
        if self.text:
            draw_text(surface, fit(self.text, self.size, rect.width), rect.topleft, self.size, self.color)


class TextField(Widget):
    def __init__(self, label, masked=False, max_len=64, placeholder=""):
        super().__init__()
        self.label = label
        self.masked = masked
        self.max_len = max_len
        self.placeholder = placeholder
        self.text = ""

    def handle(self, event):
        if event.type == pygame.TEXTINPUT:
            room = self.max_len - len(self.text)
            if room > 0:
                self.text += event.text[:room]
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return "submit"
        return None

    def draw(self, surface, rect, focused):
        _box(surface, rect, focused)
        label_w = draw_text(surface, self.label, (rect.x + 12, rect.centery), 26, DIM, "midleft").width
        x = rect.x + 24 + max(label_w, 120)
        if self.text:
            shown = "*" * len(self.text) if self.masked else self.text
            color = TEXT
        else:
            shown, color = self.placeholder, DIM
        if focused:
            shown = (shown if self.text else "") + "_"
            color = TEXT
        draw_text(surface, fit(shown, 28, rect.right - x - 12), (x, rect.centery), 28, color, "midleft")


class Choice(Widget):
    """Left/Right cycles through (value, text) options."""

    def __init__(self, label, options, index=0):
        super().__init__()
        self.label = label
        self.options = list(options)
        self.index = index

    @property
    def value(self):
        return self.options[self.index][0] if self.options else None

    def select(self, value):
        for i, (v, _) in enumerate(self.options):
            if v == value:
                self.index = i
                return

    def handle(self, event):
        if event.type == pygame.KEYDOWN and self.options:
            if event.key == pygame.K_LEFT:
                self.index = (self.index - 1) % len(self.options)
                return "changed"
            if event.key == pygame.K_RIGHT:
                self.index = (self.index + 1) % len(self.options)
                return "changed"
        return None

    def draw(self, surface, rect, focused):
        _box(surface, rect, focused)
        draw_text(surface, self.label, (rect.x + 12, rect.centery), 26, DIM, "midleft")
        text = self.options[self.index][1] if self.options else "-"
        shown = f"<  {text}  >" if focused else text
        draw_text(surface, shown, (rect.right - 14, rect.centery), 28, TEXT, "midright")


class Button(Widget):
    def __init__(self, label, action, enabled=True):
        super().__init__()
        self.label = label
        self.action = action
        self.enabled = enabled

    def handle(self, event):
        if (self.enabled and event.type == pygame.KEYDOWN
                and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER)):
            return self.action
        return None

    def draw(self, surface, rect, focused):
        _box(surface, rect, focused)
        color = (ACCENT if focused else TEXT) if self.enabled else DIM
        draw_text(surface, self.label, rect.center, 30, color, "center")


class ListView(Widget):
    """Rows of cells. Up/Down move inside it and leave it at either end; Enter picks a row."""

    def __init__(self, columns, empty_text, visible_rows=7):
        super().__init__()
        self.columns = columns          # [(header, width fraction)]
        self.empty_text = empty_text
        self.visible_rows = visible_rows
        self.rows = []                  # [(key, [cell text, ...])]
        self.selected = 0

    def set_rows(self, rows):
        keys = [k for k, _ in self.rows]
        current = keys[self.selected] if self.rows and self.selected < len(keys) else None
        self.rows = rows
        new_keys = [k for k, _ in rows]
        self.selected = new_keys.index(current) if current in new_keys else 0

    @property
    def selected_key(self):
        return self.rows[self.selected][0] if self.rows else None

    def height(self):
        return 30 + self.visible_rows * 38

    def handle(self, event):
        if event.type != pygame.KEYDOWN:
            return None
        if event.key == pygame.K_UP:
            if self.selected <= 0 or not self.rows:
                return "focus_prev"
            self.selected -= 1
        elif event.key == pygame.K_DOWN:
            if self.selected >= len(self.rows) - 1:
                return "focus_next"
            self.selected += 1
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and self.rows:
            return "pick"
        return None

    def draw(self, surface, rect, focused):
        x = rect.x
        for header, frac in self.columns:
            draw_text(surface, header, (x + 10, rect.y + 4), 24, DIM)
            x += int(rect.width * frac)
        body = pygame.Rect(rect.x, rect.y + 30, rect.width, rect.height - 30)
        pygame.draw.rect(surface, ACCENT if focused else BORDER, body, 2)
        if not self.rows:
            draw_text(surface, self.empty_text, (body.x + 14, body.y + 12), 26, DIM)
            return
        first = max(0, min(self.selected - self.visible_rows + 1, len(self.rows) - self.visible_rows))
        for n, (key, cells) in enumerate(self.rows[first:first + self.visible_rows]):
            row = pygame.Rect(body.x + 2, body.y + 2 + n * 38, body.width - 4, 36)
            if first + n == self.selected:
                pygame.draw.rect(surface, BOX_FOCUS if focused else BOX, row)
            x = row.x
            for (header, frac), cell in zip(self.columns, cells):
                width = int(rect.width * frac)
                draw_text(surface, fit(cell, 28, width - 16), (x + 8, row.centery), 28, TEXT, "midleft")
                x += width


class Form:
    def __init__(self, widgets):
        self.widgets = widgets
        self.focus = 0
        self._settle()

    def _usable(self, i):
        w = self.widgets[i]
        return w.visible and w.focusable

    def _settle(self):
        if not any(self._usable(i) for i in range(len(self.widgets))):
            return
        while not self._usable(self.focus):
            self.focus = (self.focus + 1) % len(self.widgets)

    def focused(self):
        return self.widgets[self.focus] if self.widgets else None

    def focus_on(self, widget):
        self.focus = self.widgets.index(widget)
        self._settle()

    def move(self, step):
        for _ in range(len(self.widgets)):
            self.focus = (self.focus + step) % len(self.widgets)
            if self._usable(self.focus):
                return

    def handle(self, events):
        """[(widget, action)] for this frame's events."""
        self._settle()
        actions = []
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_TAB:
                self.move(-1 if event.mod & pygame.KMOD_SHIFT else 1)
                continue
            widget = self.focused()
            if widget is None:
                continue
            if isinstance(widget, ListView) and event.type == pygame.KEYDOWN \
                    and event.key in (pygame.K_UP, pygame.K_DOWN):
                result = widget.handle(event)
                if result == "focus_prev":
                    self.move(-1)
                elif result == "focus_next":
                    self.move(1)
                continue
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_UP, pygame.K_DOWN):
                self.move(-1 if event.key == pygame.K_UP else 1)
                continue
            result = widget.handle(event)
            if result:
                actions.append((widget, result))
        return actions

    def draw(self, surface, x, y, width, gap=10):
        for i, widget in enumerate(self.widgets):
            if not widget.visible:
                continue
            h = widget.height()
            if h:
                widget.draw(surface, pygame.Rect(x, y, width, h), i == self.focus and widget.focusable)
                y += h + gap
        return y


def panel(surface, kicker, title, right_text=""):
    """The preview's "fit" panel: a centred column with a kicker, a title and an optional
    figure on the right. Returns (x, y, width) where the content starts."""
    sw, sh = surface.get_size()
    width = min(980, sw - 80)
    x = (sw - width) // 2
    y = max(40, sh // 10)
    draw_text(surface, kicker.upper(), (x, y), 24, DIM)
    draw_text(surface, title, (x, y + 22), 52, ACCENT)
    if right_text:
        draw_text(surface, right_text, (x + width, y + 30), 40, ACCENT, "topright")
    return x, y + 84, width
