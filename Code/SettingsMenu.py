import pygame


class SettingsMenu:
    """Minimal D-pad/arrow-driven settings overlay."""

    def __init__(self, settings):
        self.settings = settings
        self.visible = False
        self.selected_row = 0
        self.title_font = pygame.font.Font(None, 42)
        self.row_font = pygame.font.Font(None, 34)
        self.help_font = pygame.font.Font(None, 26)

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

    def draw(self, surface):
        if not self.visible:
            return
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        width = min(860, surface.get_width() - 80)
        height = 552
        x = (surface.get_width() - width) // 2
        y = (surface.get_height() - height) // 2
        panel_rect = pygame.Rect(x, y, width, height)
        pygame.draw.rect(surface, (30, 30, 30), panel_rect, border_radius=12)
        pygame.draw.rect(surface, (220, 220, 220), panel_rect, 2, border_radius=12)

        title = self.title_font.render("Settings (D-pad / Arrow keys)", True, (240, 240, 240))
        surface.blit(title, (x + 24, y + 18))

        rows = [
            ("Music Volume", f"{self.settings.music_volume}%"),
            ("SFX Volume", f"{self.settings.sfx_volume}%"),
            ("Environment Speed", f"{self.settings.environment_speed:.2f}x"),
            ("FPS Cap", f"{self.settings.fps_cap}"),
            ("Debug Mode", "ON" if self.settings.debug_mode else "OFF"),
            ("Faction hitbox outlines", "ON" if self.settings.debug_faction_outlines else "OFF"),
            ("Gold pickup popup", "ON" if self.settings.gold_pickup_popup else "OFF"),
        ]

        row_y = y + 90
        row_h = 58
        for i, (label, value) in enumerate(rows):
            row_rect = pygame.Rect(x + 18, row_y + i * row_h, width - 36, row_h - 8)
            if i == self.selected_row:
                pygame.draw.rect(surface, (60, 95, 130), row_rect, border_radius=8)
                pygame.draw.rect(surface, (180, 220, 255), row_rect, 2, border_radius=8)
                color = (255, 255, 255)
            else:
                color = (210, 210, 210)
            text = self.row_font.render(label, True, color)
            val = self.row_font.render(value, True, color)
            surface.blit(text, (row_rect.x + 14, row_rect.y + 11))
            surface.blit(val, (row_rect.right - val.get_width() - 14, row_rect.y + 11))

        help_text = "Up/Down select, Left/Right change, Enter toggle, Esc close"
        help_surface = self.help_font.render(help_text, True, (200, 200, 200))
        surface.blit(help_surface, (x + 24, y + height - 36))
