import pygame


class RtsInput:
    """Keyboard/d-pad style command reader for RTS mode."""

    def __init__(self, input_manager):
        self.input_manager = input_manager

    def move_direction(self):
        direction = pygame.math.Vector2(0, 0)
        if self.input_manager.is_key_pressed(pygame.K_LEFT):
            direction.x -= 1
        if self.input_manager.is_key_pressed(pygame.K_RIGHT):
            direction.x += 1
        if self.input_manager.is_key_pressed(pygame.K_UP):
            direction.y -= 1
        if self.input_manager.is_key_pressed(pygame.K_DOWN):
            direction.y += 1
        return direction

    def just_pressed_direction(self):
        direction = pygame.math.Vector2(0, 0)
        if self.input_manager.is_key_just_pressed(pygame.K_LEFT):
            direction.x -= 1
        elif self.input_manager.is_key_just_pressed(pygame.K_RIGHT):
            direction.x += 1
        if self.input_manager.is_key_just_pressed(pygame.K_UP):
            direction.y -= 1
        elif self.input_manager.is_key_just_pressed(pygame.K_DOWN):
            direction.y += 1
        return direction

    def pressed_tab(self):
        return self.input_manager.is_key_just_pressed(pygame.K_TAB)

    def pressed_confirm(self):
        return self.input_manager.is_key_just_pressed(pygame.K_RETURN)

    def pressed_cancel(self):
        return self.input_manager.is_key_just_pressed(pygame.K_ESCAPE)

    def pressed_exit(self):
        return self.input_manager.is_key_just_pressed(pygame.K_SPACE)

    def pressed_snap(self):
        return self.input_manager.is_key_just_pressed(pygame.K_HOME)
