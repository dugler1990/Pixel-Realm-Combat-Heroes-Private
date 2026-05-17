import pygame

from .actions import RtsActionQueue
from .camera import RtsCamera
from .input import RtsInput
from .resources import TribeResources
from .selection import SelectableRegistry
from .ui import RtsPanel


class RtsSession:
    """Embeddable RTS mode session.

    The session owns RTS input, camera, selection, and UI state. It talks to the
    host world only through the adapter passed at construction time.
    """

    INACTIVE = "inactive"
    CAMERA = "camera"
    SELECT = "select"
    PANEL = "panel"
    BUILD_PLACEMENT = "build_placement"
    COMMAND_TARGET = "command_target"

    def __init__(self, world_adapter, input_manager):
        self.world = world_adapter
        self.input = RtsInput(input_manager)
        self.camera = RtsCamera()
        self.selection = SelectableRegistry()
        self.panel = RtsPanel()
        self.resources = TribeResources({"gold": 0})
        self.queue = RtsActionQueue()
        self.state = self.INACTIVE
        self.throne = None

    def is_active(self):
        return self.state != self.INACTIVE

    def enter(self, throne=None):
        self.throne = throne
        focus = throne or self.world.get_player()
        self.camera.snap_to(focus)
        self.state = self.CAMERA
        self.refresh_selectables()

    def exit(self, request_stand=True):
        if request_stand:
            self.world.request_player_stand()
        self.state = self.INACTIVE
        self.selection.selected = None
        self.throne = None

    def refresh_selectables(self):
        self.selection.rebuild(self.world.get_selectable_sprites())

    def camera_focus(self):
        if self.is_active():
            return self.camera
        return self.world.get_player()

    def camera_rect(self):
        surface = self.world.get_display_surface()
        if surface is None:
            return None
        width, height = surface.get_size()
        return pygame.Rect(
            self.camera.rect.centerx - width // 2,
            self.camera.rect.centery - height // 2,
            width,
            height,
        )

    def update(self, dt):
        if not self.is_active():
            return
        if self.world.is_player_dead():
            self.state = self.INACTIVE
            return

        self.refresh_selectables()
        self.queue.update(dt)

        if self.input.pressed_exit():
            self.exit(request_stand=True)
            return
        if self.input.pressed_snap():
            self.snap_to_throne()

        if self.state == self.CAMERA:
            self._update_camera_mode(dt)
        elif self.state == self.SELECT:
            self._update_select_mode(dt)
        elif self.state == self.PANEL:
            self._update_panel_mode(dt)

    def _update_camera_mode(self, dt):
        self.camera.move(self.input.move_direction(), dt, self.world.get_map_bounds())
        if self.input.pressed_tab():
            self.state = self.SELECT
            self.selection.select_bottom_left(self.camera_rect())

    def _update_select_mode(self, dt):
        direction = self.input.just_pressed_direction()
        if direction.length_squared() > 0:
            self.selection.move_selection(direction, self.camera_rect())
        if self.input.pressed_confirm() and self.selection.selected is not None:
            self.state = self.PANEL
        elif self.input.pressed_cancel() or self.input.pressed_tab():
            self.state = self.CAMERA
            self.selection.selected = None

    def _update_panel_mode(self, dt):
        if self.input.pressed_cancel() or self.input.pressed_tab():
            self.state = self.SELECT

    def snap_to_throne(self):
        self.camera.snap_to(self.throne or self.world.get_player())
        self.camera.clamp(self.world.get_map_bounds())

    def draw(self):
        if not self.is_active():
            return
        surface = self.world.get_display_surface()
        if surface is None:
            return
        offset = self._camera_offset(surface)
        self.panel.draw_highlight(surface, self.selection.selected, offset)
        if self.state == self.PANEL:
            self.panel.draw(surface, self.selection.selected, self.resources, self.queue)
        self._draw_mode_hint(surface)

    def _camera_offset(self, surface):
        width, height = surface.get_size()
        return pygame.math.Vector2(
            self.camera.rect.centerx - width // 2,
            self.camera.rect.centery - height // 2,
        )

    def _draw_mode_hint(self, surface):
        font = pygame.font.Font(None, 24)
        if self.state == self.CAMERA:
            text = "RTS: Arrows move camera | Tab select | Home snap | Space stand"
        elif self.state == self.SELECT:
            text = "RTS Select: Arrows choose | Enter open | Tab cancel | Space stand"
        else:
            text = "RTS Panel: Esc back | Space stand"
        rendered = font.render(text, True, (240, 240, 220))
        rect = rendered.get_rect(topleft=(16, 16))
        bg = rect.inflate(16, 8)
        pygame.draw.rect(surface, (20, 20, 24), bg, border_radius=4)
        surface.blit(rendered, rect)
