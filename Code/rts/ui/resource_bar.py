import pygame

from ..categories import ALL_CATEGORIES, DISPLAY_LABELS, SIGNATURE


class ResourceBar:
    """Top HUD strip: five fixed resource slots."""

    def __init__(self):
        self.font = None
        self.small_font = None

    def _ensure_fonts(self):
        if self.font is None:
            self.font = pygame.font.Font(None, 26)
            self.small_font = pygame.font.Font(None, 20)

    def draw(self, surface, wallet, faction=None, low_food=False):
        if wallet is None:
            return
        self._ensure_fonts()
        width, _ = surface.get_size()
        slot_w = min(120, max(72, (width - 40) // 5))
        bar_h = 56
        x0 = (width - slot_w * 5) // 2
        y0 = 8
        bar_rect = pygame.Rect(x0 - 8, y0 - 4, slot_w * 5 + 16, bar_h + 8)
        pygame.draw.rect(surface, (18, 18, 24, 200), bar_rect, border_radius=6)
        pygame.draw.rect(surface, (90, 85, 70), bar_rect, 1, border_radius=6)

        signature_label = ""
        if faction is not None:
            signature_label = getattr(faction, "signature_resource_name", "")

        for i, cat in enumerate(ALL_CATEGORIES):
            x = x0 + i * slot_w
            active = wallet.is_active(cat)
            alpha = 255 if active else 90
            slot_rect = pygame.Rect(x + 4, y0, slot_w - 8, bar_h)
            pygame.draw.rect(surface, (32, 36, 44), slot_rect, border_radius=4)
            icon_color = (200, 120, 60, alpha) if cat == SIGNATURE else (100, 160, 200, alpha)
            icon = pygame.Surface((22, 22), pygame.SRCALPHA)
            icon.fill(icon_color)
            surface.blit(icon, (slot_rect.x + 6, slot_rect.y + 6))

            label = DISPLAY_LABELS.get(cat, cat.upper())
            if faction is not None:
                faction_label = faction.display_name_for_category(cat)
                if faction_label:
                    label = faction_label[:8]
            if cat == SIGNATURE and signature_label:
                label = signature_label[:8]
            label_surf = self.small_font.render(label, True, (220, 220, 210))
            surface.blit(label_surf, (slot_rect.x + 32, slot_rect.y + 4))

            amount = wallet.get(cat) if active else 0
            amt_surf = self.font.render(str(amount), True, (240, 240, 230))
            surface.blit(amt_surf, (slot_rect.x + 8, slot_rect.y + 22))

            if active:
                rate = wallet.get_rate_per_min(cat)
                if abs(rate) >= 0.05:
                    sign = "+" if rate >= 0 else ""
                    rate_text = f"{sign}{rate:.0f}/m"
                    color = (120, 200, 120) if rate >= 0 else (220, 100, 100)
                    rate_surf = self.small_font.render(rate_text, True, color)
                    surface.blit(rate_surf, (slot_rect.right - rate_surf.get_width() - 6, slot_rect.y + 26))

        if low_food:
            warn = self.small_font.render("Low food!", True, (240, 80, 80))
            surface.blit(warn, (bar_rect.centerx - warn.get_width() // 2, bar_rect.bottom + 2))
