import pygame


class DeathMenu:
    """Game-over menu: Restart (fresh run), Main Menu, Exit Game."""

    def __init__(self, game, input_manager):
        self.game = game
        self.input_manager = input_manager
        self.screen = game.screen
        self.font = pygame.font.Font(None, 44)
        self.title_font = pygame.font.Font(None, 56)
        self.options = ["Restart", "Main Menu", "Exit Game"]
        self.selected_option = 0

    def reset_selection(self):
        self.selected_option = 0

    def draw(self):
        self.screen.fill((20, 0, 0))
        title = self.title_font.render("You Died", True, (255, 80, 80))
        title_rect = title.get_rect(center=(self.game.WIDTH // 2, self.game.HEIGHT // 2 - 120))
        self.screen.blit(title, title_rect)
        for i, option in enumerate(self.options):
            color = (255, 220, 100) if i == self.selected_option else (220, 220, 220)
            text_surf = self.font.render(option, True, color)
            text_rect = text_surf.get_rect(center=(self.game.WIDTH // 2, self.game.HEIGHT // 2 + i * 55))
            self.screen.blit(text_surf, text_rect)
        hint = self.font.render("Up/Down + Enter", True, (150, 150, 150))
        hint_rect = hint.get_rect(center=(self.game.WIDTH // 2, self.game.HEIGHT // 2 + 200))
        self.screen.blit(hint, hint_rect)

    def handle_events(self):
        if self.input_manager.is_key_just_pressed(pygame.K_UP):
            self.selected_option = max(0, self.selected_option - 1)
        elif self.input_manager.is_key_just_pressed(pygame.K_DOWN):
            self.selected_option = min(len(self.options) - 1, self.selected_option + 1)
        elif self.input_manager.is_key_just_pressed(pygame.K_RETURN):
            return ("restart", "main_menu", "exit")[self.selected_option]
        return None
