import math
import pygame
from Settings import TILESIZE
from ImageCache import ImageCache
class ItemVisual(pygame.sprite.Sprite):
    def __init__(self, item, groups):
        super().__init__(groups)
        self.item = item  # Reference to the logical item
        image_raw = ImageCache.load_image(item.image_path)
        self.image = scale_image_to_tile( image_raw, TILESIZE/2 )
        self.rect = self.image.get_rect(topleft=item.pos)
        self.float_offset = item.float_offset
        self.float_direction = item.float_direction
        self.float_speed = item.float_speed
        self.float_amplitude = item.float_amplitude
        self._shake_t0 = 0
        self._shake_end = 0
        self._shake_x = 0
        self._next_shake_allowed = 0

    def start_reject_shake(self):
        """Brief horizontal wobble when pickup is rejected (e.g. inventory full)."""
        t = pygame.time.get_ticks()
        if t < self._next_shake_allowed:
            return
        self._shake_t0 = t
        self._shake_end = t + 350
        self._next_shake_allowed = t + 600

    def update(self, dt=None):
        self.float_effect()
        t = pygame.time.get_ticks()
        if t < self._shake_end:
            elapsed = t - self._shake_t0
            self._shake_x = int(8 * math.sin(elapsed * 0.08))
        else:
            self._shake_x = 0
        self.rect.x = self.item.pos[0] + self._shake_x

    def float_effect(self):
        # This method makes the item visually float up and down
        self.float_offset += self.float_direction * self.float_speed  # Adjust float speed
        if abs(self.float_offset) > self.float_amplitude:  # Adjust float range
            self.float_direction *= -1
        self.rect.y += self.float_offset

    # Should not be a part of this class really
def scale_image_to_tile(image, tile_size):
    image_width, image_height = image.get_size()
    aspect_ratio = image_width / image_height

    # Determine which dimension is more restrictive
    if aspect_ratio > 1:
        # Image is wider than tall, fit to width
        new_width = tile_size
        new_height = int(tile_size / aspect_ratio)
    else:
        # Image is taller than wide, fit to height
        new_height = tile_size
        new_width = int(tile_size * aspect_ratio)

    # Scale the image to the new dimensions
    #scaled_image = pygame.transform.scale(image, (new_width, new_height))
    scaled_image = image # ( just simplified here for now working with assets wherever possiblenot in game scaling.)
    return scaled_image
