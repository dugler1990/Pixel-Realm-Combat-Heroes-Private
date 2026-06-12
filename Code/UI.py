import pygame
from Settings import *
import os

# This is for file (images specifically) importing (This line changes the directory to where the project is saved)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

class UI:
    def __init__(self, backend):
        
        # General
        self.backend = backend
        self.font = pygame.font.Font(UI_FONT, UI_FONT_SIZE)

        # Bar Setup
        self.health_bar_rect = pygame.Rect(10, 10, HEALTH_BAR_WIDTH, BAR_HEIGHT)
        self.energy_bar_rect = pygame.Rect(10, 34, ENERGY_BAR_WIDTH, BAR_HEIGHT)
        self._exp_value = None
        self._exp_surface = None
        self._level_value = None
        self._level_surface = None

        # Convert Weapon Dictionary
        self.weapon_graphics = []
        for weapon in weapon_data.values():
            path = weapon["graphic"]
            weapon = pygame.image.load(path).convert_alpha()
            self.weapon_graphics.append(weapon)

        # Convert Magic Dictionary
        self.magic_graphics = []
        for magic in magic_data.values():
            magic = pygame.image.load(magic["graphic"]).convert_alpha()
            self.magic_graphics.append(magic)

    def show_bar(self, current, max_amount, bg_rect, color):
        # Draw Background
        self.backend.draw_rect(UI_BG_COLOR, bg_rect)

        # Converting Stats to Pixels
        ratio = current / max_amount
        current_width = bg_rect.width * ratio
        current_rect = bg_rect.copy()
        current_rect.width = current_width

        # Drawing the Bar
        self.backend.draw_rect(color, current_rect)
        self.backend.draw_rect(UI_BORDER_COLOR, bg_rect, 3)

    def show_exp(self, exp):
        exp_value = int(exp)
        if self._exp_value != exp_value or self._exp_surface is None:
            self._exp_value = exp_value
            if self._exp_surface is not None:
                self.backend.invalidate_texture(self._exp_surface)
            self._exp_surface = self.font.render(str(exp_value), False, TEXT_COLOR)
        text_surf = self._exp_surface
        x = self.backend.get_size()[0] - 20
        y = self.backend.get_size()[1] - 20
        text_rect = text_surf.get_rect(bottomright = (x, y))

        self.backend.draw_rect(UI_BG_COLOR, text_rect.inflate(20, 20))
        self.backend.blit(text_surf, text_rect, cache_key=id(text_surf))
        self.backend.draw_rect(UI_BORDER_COLOR, text_rect.inflate(20, 20), 3)

    def selection_box(self, left, top, has_switched):
        bg_rect = pygame.Rect(left, top, ITEM_BOX_SIZE, ITEM_BOX_SIZE)
        self.backend.draw_rect(UI_BG_COLOR, bg_rect)
        if has_switched:
            self.backend.draw_rect(UI_BORDER_COLOR_ACTIVE, bg_rect, 3)
        else:
            self.backend.draw_rect(UI_BORDER_COLOR, bg_rect, 3)
        return bg_rect

    def weapon_overlay(self, weapon_index, has_switched):
        bg_rect = self.selection_box(10, 630, has_switched) # Weapon Box
        weapon_surf = self.weapon_graphics[weapon_index]
        weapon_rect = weapon_surf.get_rect(center = bg_rect.center)

        self.backend.blit(weapon_surf, weapon_rect, cache_key=id(weapon_surf))

    def magic_overlay(self, magic_index, has_switched):
        bg_rect = self.selection_box(100, 630, has_switched) # Magix Box (80, 635) in Tutorial
        magic_surf = self.magic_graphics[magic_index]
        magic_rect = magic_surf.get_rect(center = bg_rect.center)

        self.backend.blit(magic_surf, magic_rect, cache_key=id(magic_surf))

    def show_level(self, level):
        if self._level_value != level or self._level_surface is None:
            self._level_value = level
            if self._level_surface is not None:
                self.backend.invalidate_texture(self._level_surface)
            self._level_surface = self.font.render(f"Level: {level}", False, TEXT_COLOR)
        level_text = self._level_surface
        x = self.backend.get_size()[0] - 20
        y =  20  # Position it above the exp display
        self.backend.blit(level_text, (x - level_text.get_width(), y), cache_key=id(level_text))


    def display(self, player):
        self.show_bar(player.health, player.stats["health"], self.health_bar_rect, HEALTH_COLOR)
        self.show_bar(player.energy, player.stats["energy"], self.energy_bar_rect, ENERGY_COLOR)
        self.show_level(player.power_level)
        self.show_exp(player.exp)

        self.weapon_overlay(player.weapon_index, not player.can_switch_weapon)
        self.magic_overlay(player.magic_index, not player.can_switch_magic)
