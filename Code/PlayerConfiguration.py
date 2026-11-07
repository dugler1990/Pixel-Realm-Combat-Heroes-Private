import pygame
import legion_ui as L

ATTRIBUTES = ("magic", "strength", "vitality", "agility", "charisma")
DERIVED = ("health", "attack", "energy", "speed")


def _shown(value):
    return f"{value:g}" if isinstance(value, float) else str(value)


class PlayerConfiguration:
    """Spending attribute points. Before the game it stands on the shrine beside the hero on the
    dais (Main2 sets `stage`); at level-up inside a level it is a framed panel on black.

    Up/Down choose, Enter spends a point (or, on Ready with none left, finishes), Backspace
    takes one back.
    """

    def __init__(self,
                 input_manager,
                 base_stats,
                 remaining_points,
                 game=None,
                 title=None):

        self.input_manager = input_manager
        self.base_stats = base_stats
        self.final_stats = base_stats.copy()
        self.remaining_points = remaining_points
        self.selected_stat_index = 0
        self.stats_list = list(ATTRIBUTES) + ["ready"]
        self.update_game_variables()
        self.finished = False
        self.title = title    # the hero's name before the game; "Level up" inside a level
        self.stage = None     # draws the shrine and the hero beneath, before the game
        self._slots = None

    def add_remaining_points(self, n):
        self.remaining_points += n

    def handle_events(self, level=None):
        if self.input_manager.is_key_just_pressed(pygame.K_DOWN):
            self.selected_stat_index = (self.selected_stat_index + 1) % len(self.stats_list)
        elif self.input_manager.is_key_just_pressed(pygame.K_UP):
            self.selected_stat_index = (self.selected_stat_index - 1) % len(self.stats_list)

        elif self.input_manager.is_key_just_pressed(pygame.K_RETURN) and self.remaining_points > 0 and self.selected_stat_index != 5:
            selected_stat = self.stats_list[self.selected_stat_index]
            self.final_stats[selected_stat] += 1
            self.remaining_points -= 1
            self.update_game_variables()

        elif self.input_manager.is_key_just_pressed(pygame.K_RETURN) and self.remaining_points == 0 and self.selected_stat_index == 5:
            if level:
                level.toggle_player_config()
                level.update_player_stats()
            self.finished = True
        elif self.input_manager.is_key_just_pressed(pygame.K_BACKSPACE):
            selected_stat = self.stats_list[self.selected_stat_index]
            # Only points spent here come back: never below the stat it started at.
            if selected_stat in self.base_stats and self.final_stats[selected_stat] > self.base_stats[selected_stat]:
                self.final_stats[selected_stat] -= 1
                self.remaining_points += 1
                self.update_game_variables()

    def update_game_variables(self):
        self.final_stats["attack"] = self.base_stats["attack"] + self.final_stats["strength"] * 2
        self.final_stats["energy"] = self.base_stats["magic"] + self.final_stats["magic"] * 50
        self.final_stats["health"] = self.base_stats["vitality"] + self.final_stats["vitality"] * 50
        self.final_stats["speed"] = self.base_stats["speed"] + self.final_stats["agility"] * 0.2

    def draw(self, backend):
        kit = L.kit_for(backend)
        if self._slots is None:
            value = lambda: L.TextSlot(backend, kit, "medium", 15, L.GOLD)  # noqa: E731
            self._slots = {key: value() for key in ATTRIBUTES + DERIVED}
            self._ready = L.TextSlot(backend, kit, "display", 16, L.TEXT, spacing=0.14, upper=True)
            self._ready_on = L.TextSlot(backend, kit, "display", 16, L.TEXT_ON, spacing=0.14, upper=True)
        pad, bar_h, gap = kit.px(30), kit.px(42), kit.px(8)
        kicker = kit.label("Attributes", "body", 13, L.GOLD, spacing=0.22, upper=True)
        width = kit.px(340) if self.stage else kit.px(400)
        titles = kit.lines(self.title or "Level up", "display", 32, L.GOLD, width - 2 * pad)
        hints = kit.lines("Enter spends a point · Backspace takes one back", "body", 12, L.GOLD,
                          width - 2 * pad, spacing=0.06)
        hint_h = sum(h.get_height() for h in hints)
        derived_h = kit.px(26)
        body = (kicker.get_height() + sum(t.get_height() - kit.px(6) for t in titles) + kit.px(14)
                + len(self.stats_list) * (bar_h + gap) + kit.px(6) + len(DERIVED) * (derived_h + 1)
                + kit.px(12) + hint_h)
        if self.stage:
            self.stage()
            margin = kit.px(28)
            panel = pygame.Rect(kit.width - margin - width, margin, width, kit.height - 2 * margin)
        else:
            height = min(kit.height - kit.px(20), body + 2 * pad)
            panel = pygame.Rect((kit.width - width) // 2, (kit.height - height) // 2, width, height)
        L.draw(backend, kit.panel(panel.w, panel.h), panel.topleft)
        inner = panel.w - 2 * pad
        x, y = panel.x + pad, panel.y + pad
        L.draw(backend, kicker, (x, y))
        y += kicker.get_height()
        for row in titles:
            L.draw(backend, row, (x, y))
            y += row.get_height() - kit.px(6)
        y += kit.px(14)
        for i, key in enumerate(self.stats_list):
            selected = i == self.selected_stat_index
            rect = pygame.Rect(x, y, inner, bar_h)
            if key == "ready":
                slot = self._ready_on if selected else self._ready
                text = "Ready" if self.remaining_points == 0 else f"{self.remaining_points} points left"
                kit.draw_bar(backend, rect, slot.surface(text), selected)
            else:
                icon = kit.icon(key, 24)
                name = kit.label(key, "display", 15, L.TEXT_ON if selected else L.TEXT, spacing=0.12, upper=True)
                extra = [(icon, (0, (bar_h - icon.get_height()) // 2)),
                         (name, (icon.get_width() + kit.px(10), (bar_h - name.get_height()) // 2))]
                value = self._slots[key].surface(_shown(self.final_stats[key]))
                kit.draw_bar(backend, rect, None, selected, value=value, extra=extra)
            y += bar_h + gap
        y += kit.px(6)
        for key in DERIVED:
            icon = kit.icon(key, 18)
            name = kit.label(key.capitalize(), "body", 14, L.MUTED)
            L.draw(backend, icon, (x, y + (derived_h - icon.get_height()) // 2))
            L.draw(backend, name, (x + kit.px(26), y + (derived_h - name.get_height()) // 2))
            self._slots[key].draw(_shown(self.final_stats[key]), (x + inner, y + derived_h // 2), "midright")
            L.draw(backend, kit.rule(inner), (x, y + derived_h))
            y += derived_h + 1
        y = panel.bottom - pad - hint_h
        for hint in hints:
            L.draw(backend, hint, (x, y))
            y += hint.get_height()
