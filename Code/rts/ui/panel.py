import pygame


class RtsPanel:
    """Simple data-driven selected-object panel and selection highlight."""

    def __init__(self):
        self.font = None
        self.small_font = None
        self.active_tab = 0

    def _ensure_fonts(self):
        if self.font is None:
            self.font = pygame.font.Font(None, 28)
            self.small_font = pygame.font.Font(None, 22)

    def draw_highlight(self, surface, selectable, camera_offset):
        if selectable is None:
            return
        rect = selectable.rect.move(-camera_offset.x, -camera_offset.y)
        inflated = rect.inflate(12, 12)
        pygame.draw.rect(surface, (255, 220, 80), inflated, 3, border_radius=4)

    def draw(self, surface, selectable, resources=None, queue=None):
        if selectable is None:
            return
        self._ensure_fonts()
        width, height = surface.get_size()
        panel_w = min(360, max(280, width // 3))
        panel_h = min(260, max(210, height - 40))
        panel = pygame.Rect(width - panel_w - 18, height - panel_h - 18, panel_w, panel_h)
        pygame.draw.rect(surface, (24, 24, 30), panel, border_radius=8)
        pygame.draw.rect(surface, (225, 205, 130), panel, 2, border_radius=8)

        x = panel.x + 14
        y = panel.y + 12
        title = self.font.render(selectable.display_name, True, (240, 235, 210))
        surface.blit(title, (x, y))
        y += 32

        image = selectable.image
        if isinstance(image, pygame.Surface):
            preview = pygame.transform.smoothscale(image, (64, 64))
            surface.blit(preview, (x, y))
        description_rect = pygame.Rect(x + 76, y, panel.width - 104, 66)
        self._draw_wrapped(surface, selectable.description, description_rect, (220, 220, 220))
        y += 78

        tab_rect = pygame.Rect(x, y, panel.width - 28, 28)
        pygame.draw.rect(surface, (48, 48, 58), tab_rect, border_radius=4)
        tab_text = self.small_font.render("Actions", True, (250, 250, 250))
        surface.blit(tab_text, (tab_rect.x + 10, tab_rect.y + 6))
        y += 38

        actions = selectable.actions or self._default_actions(selectable)
        for action in actions[:4]:
            label, cost, available = self._action_row(action, resources)
            color = (235, 235, 235) if available else (145, 145, 145)
            row = pygame.Rect(x, y, panel.width - 28, 30)
            pygame.draw.rect(surface, (36, 36, 44), row, border_radius=4)
            text = self.small_font.render(label, True, color)
            surface.blit(text, (row.x + 8, row.y + 7))
            if cost:
                cost_text = self.small_font.render(cost, True, color)
                surface.blit(cost_text, (row.right - cost_text.get_width() - 8, row.y + 7))
            y += 36

        footer = pygame.Rect(x, panel.bottom - 34, panel.width - 28, 18)
        pygame.draw.rect(surface, (14, 14, 18), footer, border_radius=4)
        progress = queue.progress() if queue is not None else 0.0
        if progress > 0:
            fill = footer.copy()
            fill.width = int(footer.width * progress)
            pygame.draw.rect(surface, (80, 180, 120), fill, border_radius=4)
        footer_text = self.small_font.render("Ready" if progress <= 0 else "Working", True, (230, 230, 230))
        surface.blit(footer_text, (footer.x + 8, footer.y + 2))

    def _draw_wrapped(self, surface, text, rect, color):
        words = str(text or "").split()
        line = ""
        y = rect.y
        for word in words:
            test = word if not line else line + " " + word
            if self.small_font.size(test)[0] <= rect.width:
                line = test
            else:
                surface.blit(self.small_font.render(line, True, color), (rect.x, y))
                y += 20
                line = word
                if y > rect.bottom - 18:
                    break
        if line and y <= rect.bottom - 18:
            surface.blit(self.small_font.render(line, True, color), (rect.x, y))

    def _default_actions(self, selectable):
        return [
            {"label": "Inspect", "description": "Review this object.", "cost": {}},
            {"label": "Hold Position", "description": "Keep current stance.", "cost": {}},
        ]

    def _action_row(self, action, resources):
        if isinstance(action, dict):
            label = action.get("label", "Action")
            cost = action.get("cost") or {}
            available = resources.can_afford(cost) if resources is not None else True
        else:
            label = getattr(action, "label", "Action")
            cost = getattr(action, "cost", {}) or {}
            available = action.is_available(resources) if hasattr(action, "is_available") else True
        cost_text = " ".join(f"{key}:{value}" for key, value in cost.items())
        return label, cost_text, available
