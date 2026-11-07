import pygame
from Settings import *
from ImageCache import ImageCache
import legion_ui as L
import os

# This is for file (images specifically) importing (This line changes the directory to where the project is saved)
os.chdir(os.path.dirname(os.path.abspath(__file__)))


class UI:
    """The HUD in the Legion look, drawn every gameplay frame: health and energy as painted
    meters top left, the level top right, experience bottom right beside the gem, the weapon and
    magic boxes bottom left in the slot frame. Every piece is kept and under 512 px a side, so
    it batches in the atlas; text is re-rendered only when its value changes."""

    def __init__(self, backend):
        self.backend = backend
        kit = self.kit = L.kit_for(backend)
        self.margin = kit.px(18)
        self.health = L.Meter(kit, kit.px(300), kit.px(26), "fill_blood.png")
        self.energy = L.Meter(kit, kit.px(220), kit.px(22), "fill_energy.png")
        self._exp = L.TextSlot(backend, kit, "display", 22, L.GOLD)
        self._level = L.TextSlot(backend, kit, "display", 18, L.GOLD, spacing=0.12, upper=True)
        self.box = kit.px(72)
        self.weapon_graphics = [weapon["graphic"] for weapon in weapon_data.values()]
        self.magic_graphics = [magic["graphic"] for magic in magic_data.values()]

    def show_bars(self, player):
        x, y = self.margin, self.margin
        self.health.draw(self.backend, (x, y), max(0.0, min(1.0, player.health / (player.stats["health"] or 1))))
        y += self.health.h + self.kit.px(6)
        self.energy.draw(self.backend, (x, y), max(0.0, min(1.0, player.energy / (player.stats["energy"] or 1))))

    def show_exp(self, exp):
        kit = self.kit
        w, h = kit.size
        rect = self._exp.draw(str(int(exp)), (w - self.margin, h - self.margin), "bottomright")
        gem = kit.icon("exp", 26)
        L.draw(self.backend, gem, (rect.x - kit.px(8) - gem.get_width(), rect.centery - gem.get_height() // 2))

    def show_level(self, level):
        self._level.draw(f"Level {level}", (self.kit.width - self.margin, self.margin), "topright")

    def selection_box(self, left, top, has_switched):
        """A slot-framed box; the gold edge while the choice can't be switched again yet."""
        bg_rect = pygame.Rect(left, top, self.box, self.box)
        if has_switched:
            edge, glow = self.kit.highlight(bg_rect.w, bg_rect.h)
            L.draw(self.backend, edge, (bg_rect.x - glow, bg_rect.y - glow))
        L.draw(self.backend, self.kit.slot(bg_rect.w, bg_rect.h), bg_rect.topleft)
        return bg_rect

    def _picture_in(self, rect, path):
        side = round(rect.w * 0.72)
        picture = self.kit.fitted(ImageCache.load_image(path), side, side, path)
        L.draw(self.backend, picture, (rect.centerx - picture.get_width() // 2, rect.centery - picture.get_height() // 2))

    def weapon_overlay(self, weapon_index, has_switched):
        top = self.kit.height - self.margin - self.box
        self._picture_in(self.selection_box(self.margin, top, has_switched), self.weapon_graphics[weapon_index])

    def magic_overlay(self, magic_index, has_switched):
        top = self.kit.height - self.margin - self.box
        left = self.margin + self.box + self.kit.px(12)
        self._picture_in(self.selection_box(left, top, has_switched), self.magic_graphics[magic_index])

    def display(self, player):
        self.show_bars(player)
        self.show_level(player.power_level)
        self.show_exp(player.exp)

        self.weapon_overlay(player.weapon_index, not player.can_switch_weapon)
        self.magic_overlay(player.magic_index, not player.can_switch_magic)
