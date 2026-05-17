import pygame


class RtsCamera:
    """Independent camera focus used while the player remains seated."""

    def __init__(self, pos=(0, 0), speed=700):
        self.pos = pygame.math.Vector2(pos)
        self.speed = float(speed)
        self.rect = pygame.Rect(0, 0, 1, 1)
        self._sync_rect()

    def _sync_rect(self):
        self.rect.center = (int(self.pos.x), int(self.pos.y))

    def snap_to(self, target):
        if hasattr(target, "rect"):
            self.pos.update(target.rect.center)
        else:
            self.pos.update(target)
        self._sync_rect()

    def move(self, direction, dt, bounds=None):
        if direction.length_squared() > 0:
            direction = direction.normalize()
            self.pos += direction * self.speed * float(dt or 0)
            self.clamp(bounds)
            self._sync_rect()

    def clamp(self, bounds):
        if bounds is None:
            return
        rect = pygame.Rect(bounds)
        self.pos.x = max(rect.left, min(rect.right, self.pos.x))
        self.pos.y = max(rect.top, min(rect.bottom, self.pos.y))
