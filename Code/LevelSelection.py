import pygame
import os
from game_logging import get_debug_logger
from ImageCache import ImageCache
from level_layouts import LEVEL_NAMES
import legion_ui as L

_game_flow_log = get_debug_logger("game_flow")

# Card position (row, column) -> level number. A picture at ../Graphics/Level/<row+1>_<col+1>.png
# makes a card.
LEVEL_AT = {
    (0, 0): 8,
    (0, 1): 7,
    (0, 2): 9,
    (0, 3): 10,  # Frostreach Expanse (PNG bootstrap)
    (1, 0): 11,  # Frostreach Sunspine Dunes 01 (painted desert)
    (1, 1): 6,
    (1, 2): 12,  # sunspine_7x6_play
}


class LevelSelection:
    """Choosing a level: the gate painting, the levels as framed cards with their names, the
    chosen one's name as the heading. Arrows move between cards, Enter begins the level; Main2
    then grows the chosen card into it (legion_ui.Grow)."""

    def __init__(self, game, input_manager):
        self.game = game
        self.input_manager = input_manager
        self.grid_columns = 4
        self.grid_rows = 3
        self.selected_option = (0, 0)  # (row, column)
        self.level_images = {}
        self.unlocked_levels_positions = self.load_level_images()
        self.selected_level = None
        self.chosen = None  # (picture, card rect) of the level just begun, for the grow
        self._kit = None

    def load_level_images(self):
        unlocked_levels = []
        for row in range(self.grid_rows):
            for col in range(self.grid_columns):
                path = f"../Graphics/Level/{row + 1}_{col + 1}.png"
                if os.path.exists(path):
                    self.level_images[(row, col)] = path
                    unlocked_levels.append((row, col))
        return unlocked_levels

    def _layout(self):
        """The heading's top-left and each card's rect, for the rows that have cards."""
        kit = self._kit
        x0, y0 = kit.px(36), kit.px(28)
        rows = max(r for r, _ in self.unlocked_levels_positions) + 1 if self.unlocked_levels_positions else 1
        top = y0 + kit.font("body", 13).get_height() + kit.font("display", 40).get_height() + kit.px(12)
        bottom = kit.height - kit.px(18) - kit.font("body", 13).get_height() - kit.px(10)
        gap = kit.px(14)
        width = (kit.width - 2 * x0 - (self.grid_columns - 1) * gap) // self.grid_columns
        height = (bottom - top - (rows - 1) * gap) // rows
        cards = {pos: pygame.Rect(x0 + pos[1] * (width + gap), top + pos[0] * (height + gap), width, height)
                 for pos in self.unlocked_levels_positions}
        return (x0, y0), cards

    def draw(self):
        backend = self.game.backend
        if self._kit is None:
            self._kit = L.kit_for(backend)
            self._scene = L.Scene(self._kit, "hall-sharp.jpg")
        kit = self._kit
        self._scene.draw(backend)
        L.draw(backend, kit.shade("vignette"), (0, 0))
        (x, y), cards = self._layout()
        number = LEVEL_AT.get(self.selected_option)
        kicker = kit.label(f"Level {number}" if number else "Level", "body", 13, L.GOLD, spacing=0.22, upper=True)
        title = kit.label(LEVEL_NAMES.get(number, ""), "display", 40, L.GOLD)
        L.draw(backend, kicker, (x, y))
        L.draw(backend, title, (x, y + kicker.get_height()))
        for pos, rect in cards.items():
            if pos == self.selected_option:
                edge, glow = kit.highlight(rect.w, rect.h)
                L.draw(backend, edge, (rect.x - glow, rect.y - glow))
            L.draw(backend, kit.covered(self.level_images[pos], rect.w, rect.h), rect.topleft)
            shade = kit.caption_shade(rect.w, rect.h)
            L.draw(backend, shade, rect.topleft)
            name = kit.label(LEVEL_NAMES.get(LEVEL_AT.get(pos), ""), "body", 14, L.TEXT)
            L.draw(backend, name, (rect.x + kit.px(14), rect.bottom - kit.px(12) - name.get_height()))
            L.draw(backend, kit.frame_over(rect.w, rect.h), rect.topleft)
        hint = kit.label("Arrows move · Enter begins the level", "body", 13, L.GOLD, spacing=0.12)
        L.draw(backend, hint, (x, kit.height - kit.px(18) - hint.get_height()))

    def handle_events(self):
        row, col = self.selected_option
        moves = {pygame.K_UP: (-1, 0), pygame.K_DOWN: (1, 0), pygame.K_LEFT: (0, -1), pygame.K_RIGHT: (0, 1)}
        for key, (dr, dc) in moves.items():
            if self.input_manager.is_key_just_pressed(key):
                target = (row + dr, col + dc)
                if target in self.unlocked_levels_positions:  # only onto a card
                    self.selected_option = target
                return
        if self.input_manager.is_key_just_pressed(pygame.K_RETURN):
            self.select_level(row, col)

    def select_level(self, row, col):
        if (row, col) not in self.unlocked_levels_positions:
            return
        selected_level = LEVEL_AT.get((row, col))
        if not selected_level:
            _game_flow_log.debug("Level at Grid %s is not available.", (row + 1, col + 1))
            return
        _game_flow_log.debug("Selected Level %s at Grid: %s", selected_level, (row + 1, col + 1))
        self.selected_level = selected_level
        if self._kit is not None:
            _, cards = self._layout()
            self.chosen = (ImageCache.load_image(self.level_images[(row, col)]), cards[(row, col)])
        self.game.in_level_selection = False
