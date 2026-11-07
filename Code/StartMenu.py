import pygame
from game_logging import get_debug_logger
import legion_ui as L

_game_flow_log = get_debug_logger("game_flow")


class StartMenu:
    """The title screen: the fortress gate in the rain, the logo, and the options as steel bars."""

    def __init__(self, game, input_manager):
        self.game = game
        self.input_manager = input_manager
        self.options = ["Start Game", "Play online", "Local co-op (dev)", "Settings"]
        self.selected_option = 0
        self.notice = ""  # one line under the options (e.g. online play not set up)
        self._kit = None

    def _look(self):
        if self._kit is None:
            backend = self.game.backend
            self._kit = L.kit_for(backend)
            self._scene = L.Scene(self._kit, "hall-sharp.jpg", rain=True, torches=L.GATE_TORCHES)
            self._notice = L.TextSlot(backend, self._kit, "body", 15, L.RED)
        return self._kit

    def draw(self):
        kit, backend = self._look(), self.game.backend
        self._scene.draw(backend)
        L.draw(backend, kit.shade("left"), (0, 0))
        L.draw(backend, kit.shade("vignette"), (0, 0))
        x, y = round(kit.width * 0.08), round(kit.height * 0.05)
        kicker = kit.label("Pixel Realm", "body", 13, L.GOLD, spacing=0.28, upper=True)
        L.draw(backend, kicker, (x, y))
        y += kicker.get_height() + kit.px(6)
        logo = kit.picture("logo.png", width=min(kit.px(500), round(kit.width * 0.38)))
        L.draw(backend, logo, (x - kit.px(10), y))
        y += logo.get_height() + kit.px(18)
        width, height, gap = kit.px(440), kit.px(46), kit.px(12)
        pressed = self.input_manager.is_key_pressed(pygame.K_RETURN)
        for i, option in enumerate(self.options):
            selected = i == self.selected_option
            label = kit.label(option, "display", 16, L.TEXT_ON if selected else L.TEXT, spacing=0.14, upper=True)
            kit.draw_bar(backend, pygame.Rect(x, y, width, height), label, selected, pressed=selected and pressed)
            y += height + gap
        hint = kit.label("Arrows move · Enter confirms", "body", 13, L.GOLD, spacing=0.12)
        L.draw(backend, hint, (x, y + kit.px(6)))
        if self.notice:
            self._notice.draw(self.notice, (x, y + kit.px(14) + hint.get_height()))

    def handle_events(self):
        if self.input_manager.is_key_just_pressed(pygame.K_UP):
            self.selected_option = max(0, self.selected_option - 1)
        elif self.input_manager.is_key_just_pressed(pygame.K_DOWN):
            self.selected_option = min(len(self.options) - 1, self.selected_option + 1)
        elif self.input_manager.is_key_just_pressed(pygame.K_RETURN):
            selected = self.options[self.selected_option]
            if selected == "Start Game":
                self.game.in_start_menu = False
            elif selected == "Play online":
                # Online play has its own screens (Main2 online_* states); no player
                # selection first -- the character is picked in the lobby.
                self.game.open_online()
            elif selected == "Local co-op (dev)":
                # Dev convenience (no env vars): proceed through the normal
                # player-selection screen, then Main2 short-circuits straight to
                # level 6 + connect. See Game._state_player_selection.
                self.game.multiplayer_pending = True
                self.game.in_start_menu = False
            elif selected == "Settings":
                _game_flow_log.debug("Settings selected")
                self.game.settings_menu.toggle()
