import pygame
import json
from game_logging import get_debug_logger
import legion_ui as L

_game_flow_log = get_debug_logger("game_flow")
with open("../Graphics/PlayerSelectionDict.json", "r") as file:
    player_dir_dict = json.loads(file.read())
_game_flow_log.debug("%s", player_dir_dict)

_players = player_dir_dict["Players"]
unlocked_player_directory = [x['player_info_dir'] for x in _players]
unlocked_player_base_stats = [x['base_stats'] for x in _players]
unlocked_player_names = [x['name'] for x in _players]
unlocked_player_display_names = [x.get('display_name', x['name'].replace("_", " ")) for x in _players]
# The full-length painting each hero stands as (Graphics/UI/kit), and the two stats on its card.
unlocked_player_paintings = [x.get('painting') for x in _players]
unlocked_player_roster_stats = [x.get('roster_stats', []) for x in _players]

STAT_ORDER = ("health", "energy", "attack", "magic", "speed", "strength", "vitality", "agility", "charisma")


def stat_value(value):
    return f"{value:g}" if isinstance(value, float) else str(value)


class PlayerSelection:
    """Choosing a hero: the shrine, the hero standing on the dais in the light, the roster as
    steel bars on the left and the hero's stats on the right. Up/Down picks, Enter chooses."""

    def __init__(self, game, input_manager):
        self.game = game
        self.input_manager = input_manager
        self.selected_option = 0
        self.selected_player_info_dir = None
        self._kit = None

    def _look(self):
        if self._kit is None:
            self._kit = L.kit_for(self.game.backend)
            self._scene = L.Scene(self._kit, "shrine.jpg")
            self.dais = L.Dais(self._kit, self._scene)
        return self._kit

    def draw_stage(self):
        """The shrine and the chosen hero on the dais; the attributes screen stands on it too."""
        self._look()
        self._scene.draw(self.game.backend)
        painting = unlocked_player_paintings[self.selected_option]
        if painting:
            self.dais.draw(self.game.backend, painting)

    def draw(self):
        kit, backend = self._look(), self.game.backend
        self.draw_stage()
        margin, pad = kit.px(28), kit.px(26)
        height = kit.height - 2 * margin

        # The roster, left.
        roster = pygame.Rect(margin, margin, kit.px(380), height)
        L.draw(backend, kit.panel(roster.w, roster.h), roster.topleft)
        x, y = roster.x + pad, roster.y + pad
        label = kit.label("Roster", "body", 12, L.GOLD, spacing=0.14, upper=True)
        L.draw(backend, label, (x, y))
        y += label.get_height() + kit.px(8)
        bar_h, face_side, gap = kit.px(64), kit.px(44), kit.px(10)
        for i, stats in enumerate(unlocked_player_base_stats):
            selected = i == self.selected_option
            extra = []
            text_x = 0
            if unlocked_player_paintings[i]:
                face = kit.head(unlocked_player_paintings[i], face_side)
                extra.append((face, (0, (bar_h - face.get_height()) // 2)))
                text_x = face_side + gap
            name = kit.label(unlocked_player_display_names[i], "display", 12,
                             L.TEXT_ON if selected else L.TEXT, spacing=0.05, upper=True)
            line = kit.label(" · ".join(f"{k.capitalize()} {stat_value(stats[k])}"
                                            for k in unlocked_player_roster_stats[i] if k in stats),
                             "body", 11, L.MUTED)
            top = (bar_h - name.get_height() - line.get_height()) // 2
            extra.append((name, (text_x, top)))
            extra.append((line, (text_x, top + name.get_height())))
            kit.draw_bar(backend, pygame.Rect(x, y, roster.w - 2 * pad, bar_h), None, selected, extra=extra)
            y += bar_h + kit.px(6)

        # The chosen hero's stats, right.
        panel = pygame.Rect(kit.width - margin - kit.px(300), margin, kit.px(300), height)
        L.draw(backend, kit.panel(panel.w, panel.h), panel.topleft)
        inner = panel.w - 2 * pad
        x, y = panel.x + pad, panel.y + pad
        kicker = kit.label("Local co-op" if self.game.multiplayer_pending else "Single player",
                           "body", 13, L.GOLD, spacing=0.22, upper=True)
        L.draw(backend, kicker, (x, y))
        y += kicker.get_height()
        for row in kit.lines(unlocked_player_display_names[self.selected_option], "display", 32, L.GOLD, inner):
            L.draw(backend, row, (x, y))
            y += row.get_height() - kit.px(6)
        y += kit.px(14)
        stats = unlocked_player_base_stats[self.selected_option]
        row_h = kit.px(28)
        for key in STAT_ORDER:
            if key not in stats:
                continue
            icon = kit.icon(key, 20)
            name = kit.label(key.capitalize(), "body", 15, L.TEXT)
            value = kit.label(stat_value(stats[key]), "medium", 15, L.GOLD)
            L.draw(backend, icon, (x, y + (row_h - icon.get_height()) // 2))
            L.draw(backend, name, (x + kit.px(30), y + (row_h - name.get_height()) // 2))
            L.draw(backend, value, (x + inner - value.get_width(), y + (row_h - value.get_height()) // 2))
            L.draw(backend, kit.rule(inner), (x, y + row_h))
            y += row_h + 1
        hints = kit.lines("Up and down choose · Enter picks", "body", 12, L.GOLD, inner, spacing=0.06)
        y = panel.bottom - pad - sum(h.get_height() for h in hints)
        for hint in hints:
            L.draw(backend, hint, (x, y))
            y += hint.get_height()

    def handle_events(self):
        count = len(unlocked_player_directory)
        if self.input_manager.is_key_just_pressed(pygame.K_UP) and self.selected_option > 0:
            self.selected_option -= 1
            self._look()
            self.dais.pick()
        elif self.input_manager.is_key_just_pressed(pygame.K_DOWN) and self.selected_option < count - 1:
            self.selected_option += 1
            self._look()
            self.dais.pick()
        elif self.input_manager.is_key_just_pressed(pygame.K_RETURN):
            self.select_player(self.selected_option)

    def select_player(self, index):
        _game_flow_log.debug("Selected player %s", unlocked_player_names[index])
        self.selected_player_info_dir = unlocked_player_directory[index]
        self.base_stats = unlocked_player_base_stats[index]
        self.game.in_player_selection = False
