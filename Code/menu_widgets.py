"""Keyboard-first menu widgets for the online screens, drawn in the Legion look.

A Form holds widgets top to bottom. Up/Down (or Tab / Shift+Tab) moves focus, Left/Right
changes a Choice, Enter presses a Button or picks a ListView row, typing goes to the
focused TextField. Drawing goes through legion_ui and the backend: buttons, choices and list
rows are steel bars (the gold one has focus), text fields are framed plaques, and `panel` is
the framed stone panel. Fixed words are kept labels; text that changes (what is typed, list
cells, notices) has one TextSlot per place, so a frame makes no surface.
"""

import pygame

import legion_ui as L

TEXT = L.TEXT
DIM = L.MUTED
ACCENT = L.GOLD
ERROR = L.RED

# Heights in the preview's pixels; Kit.px turns them into the window's.
ROW_H = 46
LIST_HEADER = 26
LIST_ROW = 40


def text_slot(owner, key, backend, kit, role, size, colour, spacing=0.0):
    """The TextSlot `owner` keeps under `key`, made the first time it is asked for."""
    slots = owner.__dict__.setdefault("_slots", {})
    slot = slots.get(key)
    if slot is None:
        slot = slots[key] = L.TextSlot(backend, kit, role, size, colour, spacing=spacing)
    return slot


def fit(kit, text, role, size, width):
    """Cut text so it renders within `width` pixels."""
    font = kit.font(role, size)
    if font.size(text)[0] <= width:
        return text
    while text and font.size(text + "...")[0] > width:
        text = text[:-1]
    return text + "..."


class Widget:
    focusable = True

    def __init__(self):
        self.visible = True

    def height(self, kit):
        return kit.px(ROW_H)

    def handle(self, event):
        """An action string, or None."""
        return None

    def draw(self, backend, kit, rect, focused):
        raise NotImplementedError


class Label(Widget):
    focusable = False

    def __init__(self, text="", color=DIM, size=15):
        super().__init__()
        self.text = text
        self.color = color
        self.size = size

    def height(self, kit):
        return kit.px(24) if self.text else 0

    def draw(self, backend, kit, rect, focused):
        if self.text:
            slot = text_slot(self, self.color, backend, kit, "body", self.size, self.color)
            slot.draw(fit(kit, self.text, "body", self.size, rect.width), rect.topleft)


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

    def draw(self, backend, kit, rect, focused):
        if focused:
            edge, glow = kit.highlight(rect.w, rect.h)
            L.draw(backend, edge, (rect.x - glow, rect.y - glow))
        L.draw(backend, kit.plaque(rect.w, rect.h), rect.topleft)
        pad = kit.px(14)
        label = kit.label(self.label, "body", 13, DIM, spacing=0.14, upper=True)
        L.draw(backend, label, (rect.x + pad, rect.centery - label.get_height() // 2))
        x = rect.x + pad + max(label.get_width(), kit.px(110)) + kit.px(12)
        if self.text:
            shown, colour = ("*" * len(self.text) if self.masked else self.text), TEXT
        else:
            shown, colour = self.placeholder, DIM
        if focused:
            shown, colour = (shown if self.text else "") + "_", TEXT
        slot = text_slot(self, colour, backend, kit, "body", 16, colour)
        slot.draw(fit(kit, shown, "body", 16, rect.right - x - pad), (x, rect.centery), "midleft")


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

    def draw(self, backend, kit, rect, focused):
        label = kit.label(self.label, "display", 15, L.TEXT_ON if focused else TEXT, spacing=0.12, upper=True)
        text = self.options[self.index][1] if self.options else "-"
        shown = f"‹  {text}  ›" if focused else text
        value = text_slot(self, "value", backend, kit, "medium", 15, ACCENT).surface(shown)
        kit.draw_bar(backend, rect, label, focused, value=value)


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

    def draw(self, backend, kit, rect, focused):
        colour = (L.TEXT_ON if focused else TEXT) if self.enabled else DIM
        label = kit.label(self.label, "display", 16, colour, spacing=0.14, upper=True)
        pressed = focused and self.enabled and pygame.key.get_pressed()[pygame.K_RETURN]
        kit.draw_bar(backend, rect, label, focused and self.enabled, pressed=pressed)


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

    def height(self, kit):
        return kit.px(LIST_HEADER) + self.visible_rows * (kit.px(LIST_ROW) + kit.px(4))

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

    def draw(self, backend, kit, rect, focused):
        row_h, gap = kit.px(LIST_ROW), kit.px(4)
        cap = kit.bar_cap(row_h) + kit.px(10)
        inner = rect.width - 2 * cap
        x = rect.x + cap
        for header, frac in self.columns:
            if header:
                L.draw(backend, kit.label(header, "body", 12, DIM, spacing=0.14, upper=True), (x, rect.y))
            x += int(inner * frac)
        top = rect.y + kit.px(LIST_HEADER)
        if not self.rows:
            empty = kit.label(self.empty_text, "body", 15, DIM)
            L.draw(backend, empty, (rect.x + cap, top + kit.px(8)))
            return
        first = max(0, min(self.selected - self.visible_rows + 1, len(self.rows) - self.visible_rows))
        for n, (key, cells) in enumerate(self.rows[first:first + self.visible_rows]):
            chosen = first + n == self.selected
            row = pygame.Rect(rect.x, top + n * (row_h + gap), rect.width, row_h)
            kit.draw_bar(backend, row, None, chosen and focused)
            x = row.x + cap
            for c, ((header, frac), cell) in enumerate(zip(self.columns, cells)):
                width = int(inner * frac)
                colour = L.TEXT_ON if chosen and focused else TEXT
                slot = text_slot(self, (n, c, colour), backend, kit, "body", 15, colour)
                slot.draw(fit(kit, cell, "body", 15, width - kit.px(12)), (x, row.centery), "midleft")
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

    def draw(self, backend, x, y, width, gap=8):
        kit = L.kit_for(backend)
        for i, widget in enumerate(self.widgets):
            if not widget.visible:
                continue
            h = widget.height(kit)
            if h:
                widget.draw(backend, kit, pygame.Rect(x, y, width, h), i == self.focus and widget.focusable)
                y += h + kit.px(gap)
        return y


def panel(backend, kicker, title, right_text=""):
    """The preview's "fit" panel: the framed stone panel over the window, a kicker, a title and
    an optional count on the right. Returns (x, y, width) where the content starts."""
    kit = L.kit_for(backend)
    margin_x, margin_top, margin_bottom = kit.px(28), kit.px(22), kit.px(18)
    rect = pygame.Rect(margin_x, margin_top, kit.width - 2 * margin_x, kit.height - margin_top - margin_bottom)
    L.draw(backend, kit.panel(rect.w, rect.h), rect.topleft)
    pad = kit.px(34)
    x, y = rect.x + pad, rect.y + pad - kit.px(6)
    head = kit.label(kicker, "body", 13, ACCENT, spacing=0.22, upper=True)
    L.draw(backend, head, (x, y))
    y += head.get_height()
    name = kit.label(title, "display", 32, ACCENT)
    L.draw(backend, name, (x, y))
    if right_text:
        count = kit.label(right_text, "display", 26, ACCENT)
        L.draw(backend, count, (rect.right - pad - count.get_width(), y + name.get_height() - count.get_height()))
    return x, y + name.get_height() + kit.px(14), rect.w - 2 * pad
