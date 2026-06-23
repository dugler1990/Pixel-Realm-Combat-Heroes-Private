"""Charge ratio HUD for held abilities."""

from __future__ import annotations

import pygame


def draw_charge_bar(backend, player, charge_ratio, *, width=80, height=8, offset_y=-40):
    if backend is None or player is None:
        return
    ratio = max(0.0, min(1.0, float(charge_ratio)))
    screen_w, screen_h = backend.get_size()
    x = int(screen_w // 2 - width // 2)
    y = int(screen_h // 2 + offset_y)
    bg = pygame.Rect(x, y, width, height)
    fill = pygame.Rect(x, y, max(1, int(width * ratio)), height)
    backend.draw_rect((40, 40, 40), bg)
    backend.draw_rect((220, 180, 40), fill)
    backend.draw_rect((255, 255, 255), bg, 1)
