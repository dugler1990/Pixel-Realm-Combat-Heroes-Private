import pygame

from ..build.catalog import buildings_for_faction


class WorkerCommandPanel:
    """D-pad worker commands: Gather, Build, Stop."""

    ROWS = ("gather", "build", "stop")

    def __init__(self):
        self.font = None
        self.small_font = None
        self.worker = None
        self.row_index = 0
        self.visible = False

    def open(self, worker):
        self.worker = worker
        self.visible = True
        self.row_index = 0

    def close(self):
        self.worker = None
        self.visible = False

    def _ensure_fonts(self):
        if self.font is None:
            self.font = pygame.font.Font(None, 28)
            self.small_font = pygame.font.Font(None, 22)

    def handle_input(self, session):
        if not self.visible or self.worker is None:
            return None
        inp = session.input
        if inp.pressed_cancel():
            self.close()
            session.state = session.SELECT
            return "closed"
        direction = inp.just_pressed_direction()
        if direction.y != 0:
            self.row_index = (self.row_index + int(direction.y)) % len(self.ROWS)
        row = self.ROWS[self.row_index]
        if inp.pressed_confirm():
            if row == "gather":
                session.pending_workers = [self.worker]
                self.close()
                session.state = session.ASSIGN_NODE
                return "gather"
            if row == "build":
                session._open_build_menu(self.worker)
                return "build"
            if row == "stop":
                session.world_sim.cancel_worker_jobs(self.worker)
                self.close()
                session.state = session.SELECT
                return "stop"
        return None

    def draw(self, surface, wallet=None):
        if not self.visible or self.worker is None:
            return
        self._ensure_fonts()
        w, h = surface.get_size()
        panel = pygame.Rect(w - 378, h - 280, 360, 260)
        pygame.draw.rect(surface, (24, 24, 30), panel, border_radius=8)
        pygame.draw.rect(surface, (225, 205, 130), panel, 2, border_radius=8)
        x = panel.x + 16
        y = panel.y + 12
        title = self.font.render("Worker Commands", True, (240, 235, 210))
        surface.blit(title, (x, y))
        y += 36
        for i, row in enumerate(self.ROWS):
            labels = {"gather": "Gather", "build": "Build", "stop": "Stop / Cancel job"}
            color = (255, 240, 180) if i == self.row_index else (200, 200, 200)
            text = self.small_font.render(labels[row], True, color)
            surface.blit(text, (x, y))
            y += 28
        hint = self.small_font.render(
            "Up/Down | Enter | Esc back", True, (180, 180, 180)
        )
        surface.blit(hint, (x, panel.bottom - 28))


class BuildMenuPanel:
    """List faction buildings and costs."""

    def __init__(self):
        self.font = None
        self.small_font = None
        self.worker = None
        self.entries = []
        self.row_index = 0
        self.visible = False

    def open(self, worker, faction_id, wallet):
        self.worker = worker
        self.entries = buildings_for_faction(faction_id)
        self.row_index = 0
        self.visible = True
        self._wallet = wallet

    def close(self):
        self.worker = None
        self.entries = []
        self.visible = False

    def selected_building(self):
        if not self.entries:
            return None
        return self.entries[self.row_index % len(self.entries)]

    def _ensure_fonts(self):
        if self.font is None:
            self.font = pygame.font.Font(None, 28)
            self.small_font = pygame.font.Font(None, 22)

    def handle_input(self, session):
        if not self.visible or not self.entries:
            return None
        inp = session.input
        if inp.pressed_cancel():
            self.close()
            session.state = session.WORKER_MENU
            session.worker_command_panel.open(session._worker_menu_worker)
            return "back"
        direction = inp.just_pressed_direction()
        if direction.y != 0:
            self.row_index = (self.row_index + int(direction.y)) % len(self.entries)
        if inp.pressed_confirm():
            building = self.selected_building()
            if building is None:
                return None
            wallet = session.wallet
            if wallet is not None and not wallet.can_afford(building.cost):
                return None
            session._open_pick_build_site(self.worker, building)
            return "pick_site"
        return None

    def draw(self, surface):
        if not self.visible:
            return
        self._ensure_fonts()
        w, h = surface.get_size()
        panel = pygame.Rect(w - 378, h - 300, 360, 280)
        pygame.draw.rect(surface, (24, 24, 30), panel, border_radius=8)
        pygame.draw.rect(surface, (225, 205, 130), panel, 2, border_radius=8)
        x = panel.x + 16
        y = panel.y + 12
        surface.blit(self.font.render("Build", True, (240, 235, 210)), (x, y))
        y += 32
        wallet = getattr(self, "_wallet", None)
        for i, building in enumerate(self.entries):
            affordable = wallet is None or wallet.can_afford(building.cost)
            color = (255, 240, 180) if i == self.row_index else (200, 200, 200)
            if not affordable:
                color = (140, 100, 100) if i == self.row_index else (100, 100, 100)
            cost_parts = [f"{k}:{v}" for k, v in building.cost.items()]
            cost_text = "free" if not cost_parts else " ".join(cost_parts)
            line = f"{building.label} ({cost_text})"
            surface.blit(self.small_font.render(line[:42], True, color), (x, y))
            y += 24
        hint = self.small_font.render("Enter: pick site | Esc: back", True, (180, 180, 180))
        surface.blit(hint, (x, panel.bottom - 28))
