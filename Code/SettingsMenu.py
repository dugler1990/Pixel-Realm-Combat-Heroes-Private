import pygame
import legion_ui as L


class SettingsMenu:
    """The settings overlay, over any screen: a framed panel of steel bars, one per setting,
    with its value on the right. Up/Down select, Left/Right change, Enter toggles, Esc closes."""

    def __init__(self, settings):
        self.settings = settings
        self.visible = False
        self.selected_row = 0

    def toggle(self):
        self.visible = not self.visible

    def handle_events(self, events):
        if not self.visible:
            return
        for event in events:
            if event.type != pygame.KEYDOWN:
                continue
            if event.key == pygame.K_ESCAPE:
                self.visible = False
            elif event.key == pygame.K_UP:
                self.selected_row = max(0, self.selected_row - 1)
            elif event.key == pygame.K_DOWN:
                self.selected_row = min(len(self.settings.MENU_ROWS) - 1, self.selected_row + 1)
            elif event.key == pygame.K_LEFT:
                self.settings.step_left(self.settings.MENU_ROWS[self.selected_row])
            elif event.key == pygame.K_RIGHT:
                self.settings.step_right(self.settings.MENU_ROWS[self.selected_row])
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self.settings.activate_row(self.settings.MENU_ROWS[self.selected_row])

    def _rows(self):
        s = self.settings
        return [
            ("Music", f"{s.music_volume}%"),
            ("Effects", f"{s.sfx_volume}%"),
            ("Environment", f"{s.environment_speed:.2f}x"),
            ("Frame cap", f"{s.fps_cap}"),
            ("Debug", "On" if s.debug_mode else "Off"),
            ("Faction outlines", "On" if s.debug_faction_outlines else "Off"),
            ("Gold popup", "On" if s.gold_pickup_popup else "Off"),
            ("Speech bubbles", "On" if s.speech_bubbles else "Off"),
            ("Conversation text", "On" if s.conversation_text else "Off"),
            ("Voice", "On" if s.voice_enabled else "Off"),
        ]

    def draw(self, backend):
        """Over whatever Main2 drew beneath. Values come from a small fixed set of strings, so
        each is a kept label."""
        if not self.visible:
            return
        kit = L.kit_for(backend)
        L.draw(backend, kit.shade("dim"), (0, 0))
        rows = self._rows()
        bar_h, gap = kit.px(40), kit.px(8)
        pad = kit.px(34)
        kicker = kit.label("Settings", "body", 13, L.GOLD, spacing=0.22, upper=True)
        title = kit.label("Options", "display", 40, L.GOLD)
        hint = kit.label("Left and right change a value · Esc closes", "body", 13, L.GOLD, spacing=0.1)
        width = min(kit.px(640), kit.width - kit.px(64))
        height = (2 * pad + kicker.get_height() + title.get_height() + kit.px(12)
                  + len(rows) * (bar_h + gap) + kit.px(10) + hint.get_height())
        x, y = (kit.width - width) // 2, (kit.height - height) // 2
        L.draw(backend, kit.panel(width, height), (x, y))
        cx, cy = x + pad, y + pad
        L.draw(backend, kicker, (cx, cy))
        cy += kicker.get_height()
        L.draw(backend, title, (cx, cy))
        cy += title.get_height() + kit.px(12)
        for i, (name, value) in enumerate(rows):
            selected = i == self.selected_row
            colour = L.TEXT_ON if selected else L.TEXT
            label = kit.label(name, "display", 15, colour, spacing=0.12, upper=True)
            shown = kit.label(value, "medium", 15, L.GOLD)
            kit.draw_bar(backend, pygame.Rect(cx, cy, width - 2 * pad, bar_h), label, selected, value=shown)
            cy += bar_h + gap
        L.draw(backend, hint, (cx, cy + kit.px(10) - gap))
