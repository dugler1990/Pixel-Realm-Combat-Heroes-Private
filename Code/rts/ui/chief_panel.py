import pygame


class ChiefPanel:
    ROWS = ("idle", "workers", "fighters")

    def __init__(self):
        self.font = None
        self.small_font = None
        self.chief = None
        self.row_index = 0
        self.visible = False

    def open(self, chief):
        self.chief = chief
        self.visible = True
        self.row_index = 0
        if chief is not None:
            chief.interacting = True

    def close(self):
        if self.chief is not None:
            self.chief.interacting = False
        self.chief = None
        self.visible = False

    def _ensure_fonts(self):
        if self.font is None:
            self.font = pygame.font.Font(None, 28)
            self.small_font = pygame.font.Font(None, 22)

    def handle_input(self, session):
        if not self.visible or self.chief is None:
            return None
        inp = session.input
        if inp.pressed_cancel():
            self.close()
            session.state = session.SELECT
            return "closed"
        direction = inp.just_pressed_direction()
        if direction.y != 0:
            self.row_index = (self.row_index + int(direction.y)) % len(self.ROWS)
        row_key = self.ROWS[self.row_index]
        if row_key == "workers":
            if direction.x > 0:
                session.spawn_worker_from_chief(self.chief)
            elif direction.x < 0:
                session.despawn_worker_from_chief(self.chief)
        if inp.input_manager.is_key_just_pressed(pygame.K_a):
            faction_id = self.chief.faction_id
            self.close()
            session.select_all_workers(faction_id)
            session.state = session.SELECT
            return "select_all"
        return None

    def draw(self, surface):
        if not self.visible or self.chief is None:
            return
        self._ensure_fonts()
        chief = self.chief
        w, h = surface.get_size()
        panel = pygame.Rect(w // 2 - 160, h // 2 - 130, 320, 260)
        pygame.draw.rect(surface, (24, 24, 30), panel, border_radius=8)
        pygame.draw.rect(surface, (225, 205, 130), panel, 2, border_radius=8)
        x = panel.x + 16
        y = panel.y + 12
        title = self.font.render(
            f"{chief.display_name} — {chief.faction_id}", True, (240, 235, 210)
        )
        surface.blit(title, (x, y))
        y += 36
        total = self.small_font.render(
            f"Total People: {chief.population_total}", True, (220, 220, 220)
        )
        surface.blit(total, (x, y))
        y += 32
        rows = [
            ("Idle", chief.population_idle),
            ("Workers", chief.population_workers),
            ("Fighters", chief.population_fighters),
        ]
        for i, (label, value) in enumerate(rows):
            color = (255, 240, 180) if i == self.row_index else (200, 200, 200)
            row_text = self.small_font.render(
                f"{label:<10} {value:>3}   <  >", True, color
            )
            surface.blit(row_text, (x, y))
            y += 28
        hint = self.small_font.render(
            "Up/Down row | L/R adjust workers | A: all workers | Esc", True, (180, 180, 180)
        )
        surface.blit(hint, (x, panel.bottom - 28))
