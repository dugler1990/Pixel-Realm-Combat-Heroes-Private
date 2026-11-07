import pygame
import legion_ui as L


class DeathMenu:
    """Game-over menu: Restart (fresh run), Main Menu, Exit Game. The fortress gate under a red
    shade, and a framed panel in the middle."""

    def __init__(self, game, input_manager):
        self.game = game
        self.input_manager = input_manager
        self.options = ["Restart", "Main Menu", "Exit Game"]
        self.selected_option = 0
        self._kit = None

    def reset_selection(self):
        self.selected_option = 0

    def draw(self):
        backend = self.game.backend
        if self._kit is None:
            self._kit = L.kit_for(backend)
            self._scene = L.Scene(self._kit, "hall-sharp.jpg", rain=True, torches=L.GATE_TORCHES)
        kit = self._kit
        self._scene.draw(backend)
        L.draw(backend, kit.shade("death"), (0, 0))
        L.draw(backend, kit.shade("vignette"), (0, 0))
        bar_h, gap, pad = kit.px(46), kit.px(12), kit.px(30)
        kicker = kit.label("Fallen", "body", 13, L.GOLD, spacing=0.22, upper=True)
        title = kit.label("You died", "display", 40, L.GOLD)
        width = kit.px(380)
        height = 2 * pad + kicker.get_height() + title.get_height() + kit.px(14) + len(self.options) * (bar_h + gap) - gap
        x, y = (kit.width - width) // 2, (kit.height - height) // 2
        L.draw(backend, kit.panel(width, height), (x, y))
        cx, cy = x + pad, y + pad
        L.draw(backend, kicker, (cx, cy))
        cy += kicker.get_height()
        L.draw(backend, title, (cx, cy))
        cy += title.get_height() + kit.px(14)
        pressed = self.input_manager.is_key_pressed(pygame.K_RETURN)
        for i, option in enumerate(self.options):
            selected = i == self.selected_option
            label = kit.label(option, "display", 16, L.TEXT_ON if selected else L.TEXT, spacing=0.14, upper=True)
            kit.draw_bar(backend, pygame.Rect(cx, cy, width - 2 * pad, bar_h), label, selected,
                         pressed=selected and pressed)
            cy += bar_h + gap

    def handle_events(self):
        if self.input_manager.is_key_just_pressed(pygame.K_UP):
            self.selected_option = max(0, self.selected_option - 1)
        elif self.input_manager.is_key_just_pressed(pygame.K_DOWN):
            self.selected_option = min(len(self.options) - 1, self.selected_option + 1)
        elif self.input_manager.is_key_just_pressed(pygame.K_RETURN):
            return ("restart", "main_menu", "exit")[self.selected_option]
        return None
