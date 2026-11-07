import pygame
import legion_ui as L


def _hero_of(player):
    """The painting and name of the player's hero, found by its folder."""
    # Imported here: the headless server loads levels (and so this module) without the menus.
    from PlayerSelection import unlocked_player_directory, unlocked_player_display_names, unlocked_player_paintings
    folder = str(getattr(getattr(player, "level", None), "selected_player_info_dir", "") or "").rstrip("/\\")
    for path, painting, name in zip(unlocked_player_directory, unlocked_player_paintings, unlocked_player_display_names):
        if path.rstrip("/\\") == folder:
            return painting, name
    return None, "Upgrade"


class Upgrade:
    """Spending experience on stats inside a level (P): a framed panel, the hero standing on the
    left, one steel bar per stat with its icon, its cost, its value and a gold meter, and the
    experience held top right beside the gem. Up/Down choose, Space buys, P closes."""

    def __init__(self, player, input_manager, backend):
        self.input_manager = input_manager
        self.player = player
        self.backend = backend
        self.attribute_names = list(player.upgrade_stat_order)
        self.attribute_nr = len(self.attribute_names)
        self.max_values = [player.max_stats[k] for k in player.upgrade_stat_order]
        self.selection_index = 0
        self.selection_time = None
        self.can_move = True
        self.pause_debounce_time = 0
        self._slots = None
        self._meters = {}

    def input(self):
        current_time = pygame.time.get_ticks()
        if self.can_move:
            # The stats are stacked, so Down and Up move between them.
            if self.input_manager.is_key_pressed(pygame.K_DOWN) and self.selection_index < self.attribute_nr - 1:
                self.selection_index += 1
                self.can_move = False
                self.selection_time = current_time
            elif self.input_manager.is_key_pressed(pygame.K_UP) and self.selection_index > 0:
                self.selection_index -= 1
                self.can_move = False
                self.selection_time = current_time

            if self.input_manager.is_key_pressed(pygame.K_SPACE):
                self.can_move = False
                self.selection_time = current_time
                self.trigger(self.selection_index)

            if self.input_manager.is_key_just_pressed(pygame.K_p):
                if (current_time - self.pause_debounce_time > 500) and (self.player.level.upgrade_menu_open == self.player.level.game_paused):
                    self.player.level.toggle_menu()
                    self.pause_debounce_time = current_time

    def trigger(self, index):
        player = self.player
        upgrade_attribute = player.upgrade_stat_order[index]
        cur = player.stats.get(upgrade_attribute, 0)
        cap = player.max_stats[upgrade_attribute]
        if player.exp >= player.upgrade_cost[upgrade_attribute] and cur < cap:
            player.exp -= player.upgrade_cost[upgrade_attribute]
            player.stats[upgrade_attribute] = cur * 1.2
            player.upgrade_cost[upgrade_attribute] *= 1.4
        if player.stats.get(upgrade_attribute, 0) > cap:
            player.stats[upgrade_attribute] = cap

    def selection_cooldown(self):
        if not self.can_move:
            current_time = pygame.time.get_ticks()
            if current_time - self.selection_time >= 300:
                self.can_move = True

    def _meter(self, kit, w, h):
        meter = self._meters.get((w, h))
        if meter is None:
            meter = self._meters[(w, h)] = L.Meter(kit, w, h, "fill_gold.png")
        return meter

    def display(self):
        self.input()
        self.selection_cooldown()
        backend, kit, player = self.backend, L.kit_for(self.backend), self.player
        if self._slots is None:
            self._purse = L.TextSlot(backend, kit, "display", 28, L.GOLD)
            self._values = [L.TextSlot(backend, kit, "body", 14, L.TEXT) for _ in self.attribute_names]
            self._costs = [L.TextSlot(backend, kit, "medium", 14, L.GOLD) for _ in self.attribute_names]
            self._slots = True
        painting, name = _hero_of(player)

        width = min(kit.width - kit.px(56), round((kit.height - kit.px(40)) * 1.5))
        panel = pygame.Rect(0, 0, width, round(width / 1.5))
        panel.center = (kit.width // 2, kit.height // 2)
        L.draw(backend, kit.panel(panel.w, panel.h), panel.topleft)
        pad = kit.px(30)
        inner = panel.inflate(-2 * pad, -2 * pad)

        # The hero, standing in a pool of warm light on the left.
        hero_w = round(inner.w * 0.3)
        if painting:
            figure = kit.picture(painting, height=round(inner.h * 0.94))
            pool = kit.pool(round(hero_w * 1.2), round(inner.h * 0.16))
            L.draw(backend, pool, (inner.x + hero_w / 2 - pool.get_width() / 2, inner.bottom - pool.get_height()))
            L.draw(backend, figure, (inner.x + hero_w / 2 - figure.get_width() / 2, inner.bottom - figure.get_height() - kit.px(8)))

        # The heading and the experience held.
        x = inner.x + hero_w + kit.px(26)
        column = inner.right - x
        y = inner.y
        kicker = kit.label("Upgrade", "body", 13, L.GOLD, spacing=0.22, upper=True)
        L.draw(backend, kicker, (x, y))
        title = kit.label(name, "display", 32, L.GOLD)
        L.draw(backend, title, (x, y + kicker.get_height()))
        gem = kit.icon("exp", 34)
        purse = self._purse.surface(str(int(player.exp)))
        L.draw(backend, purse, (inner.right - purse.get_width(), y + kicker.get_height()))
        L.draw(backend, gem, (inner.right - purse.get_width() - kit.px(8) - gem.get_width(),
                              y + kicker.get_height() + (purse.get_height() - gem.get_height()) // 2))
        y += kicker.get_height() + title.get_height() + kit.px(12)

        # One bar per stat: icon, name, cost and value on top, the meter below.
        bar_h, gap = kit.px(74), kit.px(4)
        icon_side = kit.px(44)
        cap = kit.bar_cap(bar_h) + kit.px(10)
        meter_h = kit.px(22)
        for i, key in enumerate(self.attribute_names):
            selected = i == self.selection_index
            rect = pygame.Rect(x, y, column, bar_h)
            icon = kit.icon(key, 44)
            label = kit.label(key, "display", 14, L.TEXT_ON if selected else L.TEXT, spacing=0.12, upper=True)
            value = self._values[i].surface(f"{round(player.get_value_by_index(i))} / {self.max_values[i]}")
            cost = self._costs[i].surface(str(int(player.get_cost_by_index(i))))
            small_gem = kit.icon("exp", 16)
            text_x = icon_side + kit.px(14)
            top = kit.px(10)
            right = rect.w - 2 * cap
            extra = [
                (icon, ((icon_side - icon.get_width()) // 2, (bar_h - icon.get_height()) // 2)),
                (label, (text_x, top)),
                (value, (right - value.get_width(), top)),
                (cost, (right - value.get_width() - kit.px(24) - cost.get_width(), top)),
                (small_gem, (right - value.get_width() - kit.px(28) - cost.get_width() - small_gem.get_width(),
                             top + (cost.get_height() - small_gem.get_height()) // 2)),
            ]
            kit.draw_bar(backend, rect, None, selected, extra=extra)
            ratio = player.get_value_by_index(i) / self.max_values[i] if self.max_values[i] else 0
            meter_w = right - text_x
            self._meter(kit, meter_w, meter_h).draw(backend, (rect.x + cap + text_x, rect.bottom - meter_h - kit.px(12)),
                                                    min(1.0, max(0.0, ratio)))
            y += bar_h + gap

        hint = kit.label("Up and down choose · Space buys · P closes", "body", 12, L.GOLD, spacing=0.1)
        L.draw(backend, hint, (x, inner.bottom - hint.get_height()))
