import pygame
import math

class DaytimeBrightnessOverlay:
    def __init__(self, backend=None):
        self.backend = backend
        self.current_time = 0  # Current time of day in hours
        self.brightness = 1.0  # Default brightness
        self.day_length = 24  # Total length of a day in hours
        self.min_brightness = 0.22  # Minimum brightness value

    def set_time_of_day(self, current_time):
        # Set the current time of day
        self.current_time = current_time
       # print(f"BRIGHTNESS CURRENT TIME : {self.current_time}")
        # Calculate brightness based on the time of day
        self.calculate_brightness()
        
    def set_backend(self, backend):
        self.backend = backend

    def set_display_surface(self, display_surface):
        """Deprecated Phase 0 — use set_backend."""
        from render_backend import CPUBackend
        self.backend = CPUBackend(display_surface)

    def calculate_brightness(self):
        # Calculate brightness based on the time of day
        # Daytime (6:00 to 18:00)
        if 12 <= self.current_time < 18:
            self.brightness = 1.0  # Full brightness
        # Transition from Day to Night (18:00 to 0:00)
        elif 18 <= self.current_time < 24:
            transition_time = self.current_time - 18
            # Smooth transition from 1.0 to min_brightness over 6 hours
            self.brightness = 1.0 - (transition_time / 6) * (1.0 - self.min_brightness)
            self.brightness = max(self.min_brightness, self.brightness)
        # Nighttime (0:00 to 6:00)
        elif 0 <= self.current_time < 6:
            self.brightness = self.min_brightness  # Minimum brightness
        # Transition from Night to Day (6:00 to 12:00)
        elif 6 <= self.current_time < 12:
            transition_time = self.current_time - 6  # Adjust for 6:00 start
            # Smooth transition from min_brightness to 1.0 over 6 hours
            self.brightness = self.min_brightness + (transition_time / 6) * (1.0 - self.min_brightness)
            self.brightness = min(1.0, self.brightness)


    def draw(self):
        if self.backend is None:
            return
        v = int(255 * self.brightness)
        self.backend.fill((v, v, v), flags=pygame.BLEND_RGB_MULT)
