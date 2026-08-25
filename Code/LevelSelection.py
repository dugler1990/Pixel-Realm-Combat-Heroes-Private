import pygame
import os
from game_logging import get_debug_logger

_game_flow_log = get_debug_logger("game_flow")
class LevelSelection:
    def __init__(self, game, input_manager):
        self.game = game
        self.input_manager = input_manager
        self.grid_columns = 4
        self.grid_rows = 3
        backend_width, backend_height = self.game.backend.get_size()
        self.grid_size = backend_width // self.grid_columns, backend_height // self.grid_rows
        self.selected_option = (0, 0)  # (row, column)
        self.level_images = {}
        self.unlocked_levels_positions = self.load_level_images()
        self.selected_level = None

    def load_level_images(self):
        unlocked_levels = []
        for row in range(self.grid_rows):
            for col in range(self.grid_columns):
                level_image_path = f"../Graphics/Level/{row+1}_{col+1}.png"
                if os.path.exists(level_image_path):
                    self.level_images[(row, col)] = pygame.image.load(level_image_path)
                    unlocked_levels.append((row, col))
        return unlocked_levels

    def draw_grid(self, surface):
        for row in range(self.grid_rows):
            for col in range(self.grid_columns):
                rect = pygame.Rect(col * self.grid_size[0], row * self.grid_size[1], self.grid_size[0], self.grid_size[1])
                pygame.draw.rect(surface, (255, 255, 255) if (row, col) == self.selected_option else (100, 100, 100), rect, 2 if (row, col) == self.selected_option else 1)
                if (row, col) in self.level_images:
                    surface.blit(pygame.transform.scale(self.level_images[(row, col)], self.grid_size), (rect.x, rect.y))

    def draw(self):
        surface = self.game.backend.compose()
        surface.fill((0, 0, 0))  # Clear screen
        self.draw_grid(surface)
        self.game.backend.blit(surface, (0, 0))


    def handle_events(self):
        row, col = self.selected_option
        if self.input_manager.is_key_just_pressed(pygame.K_UP) and row > 0:
            self.selected_option = (row - 1, col)
        elif self.input_manager.is_key_just_pressed(pygame.K_DOWN) and row < self.grid_rows - 1:
            self.selected_option = (row + 1, col)
        elif self.input_manager.is_key_just_pressed(pygame.K_LEFT) and col > 0:
            self.selected_option = (row, col - 1)
        elif self.input_manager.is_key_just_pressed(pygame.K_RIGHT) and col < self.grid_columns - 1:
            self.selected_option = (row, col + 1)
        elif self.input_manager.is_key_just_pressed(pygame.K_RETURN):
            self.select_level(row, col)

    def select_level(self, row, col):
        level_map = {
            (0, 0): 8,  # Top-left grid starts level 1
             (0, 1): 7,  # Top row, second column starts level 2
             (0, 2): 9,
             (0, 3): 10,  # Frostreach Expanse (PNG bootstrap)
             (1, 0): 11,  # Frostreach Sunspine Dunes 01 (painted desert)
             (1, 2): 12,  # sunspine_7x6_play
             (1,1):6,
            # (1, 0): 4,
            # (1, 1): 5,
            # (1, 2): 7,
         # Add more mappings as needed
        }
        if (row, col) in self.unlocked_levels_positions:
            selected_level = level_map.get((row, col))
            if selected_level:
                _game_flow_log.debug(
                    "Selected Level %s at Grid: %s",
                    selected_level,
                    (row + 1, col + 1),
                )
                self.selected_level = selected_level
                self.game.in_level_selection = False
            else:
                _game_flow_log.debug(
                    "Level at Grid %s is not available.", (row + 1, col + 1)
                )

