"""GPU day/night lighting (Phase L).

One LightingManager owns the whole day/night model: a time-of-day ambient darkness
floor plus additive radial light sources (player vision pool, torches, and any
registered fires/spells), composited as a multiply light-map by the GPU backend.

Render each frame:
    lighting.render(backend, time_of_day, camera_offset, screen_size,
                    torches=<Torch sprites>, player_center=(W//2, H//2))

Generalizable: drop in extra lights with lighting.add_light(LightSource(...)).
"""
import math
import random
from dataclasses import dataclass, field

import pygame


@dataclass
class LightSource:
    """A registered light (fire, spell, prop). Position is world pixels unless
    screen_centered (then it tracks the player_center passed to render)."""
    x: float = 0.0
    y: float = 0.0
    radius: float = 150.0
    color: tuple = (1.0, 0.95, 0.8)   # warm white
    intensity: float = 1.0
    flicker: float = 0.0              # 0 = steady; else amplitude (fraction of intensity)
    flicker_speed: float = 0.010      # radians per millisecond
    screen_centered: bool = False
    _phase: float = field(default_factory=lambda: random.uniform(0.0, 1000.0))


class LightingManager:
    MIN_AMBIENT = 0.22  # darkness floor (matches old DaytimeBrightnessOverlay.min_brightness)

    def __init__(self, backend=None):
        self.backend = backend
        self._registry = []  # persistent LightSources (fires, spells, ...)

        # Player vision pool — radius/intensity grow as it gets darker (Diablo-2 style).
        self.player_color = (1.0, 0.93, 0.78)
        self.player_radius_day = 0.0
        self.player_radius_dark = 260.0
        self.player_intensity_day = 0.6
        self.player_intensity_dark = 1.2

        # Torch defaults (warm, gently flickering).
        self.torch_color = (1.0, 0.7, 0.35)
        self.torch_radius = 150.0
        self.torch_intensity = 1.2
        self.torch_flicker = 0.12
        self.torch_flicker_speed = 0.012

        # Sun/moon directional-shadow tunables (visual iteration expected).
        self.shadow_day_strength = 0.45     # alpha of shadows in full daylight
        self.shadow_night_strength = 0.12   # faint moon shadow at night
        self.shadow_len_min = 0.35          # shadow length at noon, x sprite height
        self.shadow_len_max = 1.8           # shadow length at dawn/dusk, x sprite height
        self.shadow_max_lean = 1.1          # radians of horizontal lean at dawn/dusk

    def set_backend(self, backend):
        self.backend = backend

    # ---- generalizable light registry --------------------------------------
    def add_light(self, light):
        """Register a persistent light (e.g. a fire). Returns it for later removal."""
        self._registry.append(light)
        return light

    def remove_light(self, light):
        if light in self._registry:
            self._registry.remove(light)

    # ---- time of day -------------------------------------------------------
    def ambient_at(self, t):
        """Ambient brightness [MIN_AMBIENT, 1] by hour-of-day (same curve as the old
        DaytimeBrightnessOverlay and Weather.light_level)."""
        lo = self.MIN_AMBIENT
        if 12 <= t < 18:
            return 1.0
        if 18 <= t < 24:
            return max(lo, 1.0 - (t - 18) / 6 * (1.0 - lo))
        if 0 <= t < 6:
            return lo
        return min(1.0, lo + (t - 6) / 6 * (1.0 - lo))  # 6..12

    def sun_shadow(self, t):
        """Directional shadow params for the hour-of-day: (dir_x, dir_y, length_scale,
        strength). dir is a unit vector pointing from a caster's feet toward where its
        shadow falls (down-screen, leaning with the sun's azimuth). length_scale
        multiplies the caster's sprite height; strength is the shadow alpha.
        Long & leaning at dawn/dusk, short near noon, faint 'moon' at night."""
        if 7 <= t < 17:
            day = 1.0
        elif 5 <= t < 7:
            day = (t - 5) / 2.0
        elif 17 <= t < 19:
            day = (19 - t) / 2.0
        else:
            day = 0.0
        strength = self.shadow_night_strength + (self.shadow_day_strength - self.shadow_night_strength) * day

        # Lean & length ease in with `day` so night is a short, straight moon shadow and
        # there's no snap at the 6:00/18:00 boundaries.
        nf = max(-1.0, min(1.0, (t - 12.0) / 6.0))             # -1 dawn .. 0 noon .. +1 dusk
        elev = math.cos(nf * math.pi / 2.0)                    # 1 at noon, 0 at dawn/dusk
        length_day = self.shadow_len_min + (self.shadow_len_max - self.shadow_len_min) * (1.0 - elev)
        length_scale = self.shadow_len_min + (length_day - self.shadow_len_min) * day
        lean = nf * self.shadow_max_lean * day
        return (math.sin(lean), math.cos(lean), length_scale, strength)

    # ---- per-frame render --------------------------------------------------
    def render(self, backend, time_of_day, offset, screen_size, torches=(), player_center=None):
        ambient = self.ambient_at(time_of_day)
        if ambient >= 0.999:
            return  # full daylight: multiply-by-1 is a no-op, skip the whole pass

        w, h = screen_size
        ox, oy = offset
        # 0 at full day -> 1 at full dark
        dark = (1.0 - ambient) / (1.0 - self.MIN_AMBIENT)
        ticks = pygame.time.get_ticks()

        backend.begin_light_pass(ambient)

        # Player vision pool
        if player_center is not None:
            pr = self.player_radius_day + (self.player_radius_dark - self.player_radius_day) * dark
            pi = self.player_intensity_day + (self.player_intensity_dark - self.player_intensity_day) * dark
            self._emit(backend, player_center[0], player_center[1], pr, self.player_color, pi, w, h)

        # Torches (from the visible Torch sprites)
        for t in torches:
            fl = 1.0 + self.torch_flicker * math.sin(ticks * self.torch_flicker_speed + (id(t) % 997))
            self._emit(backend, t.rect.centerx - ox, t.rect.centery - oy,
                       self.torch_radius, self.torch_color, self.torch_intensity * fl, w, h)

        # Registered generic lights
        for L in self._registry:
            if L.screen_centered and player_center is not None:
                lx, ly = player_center
            else:
                lx, ly = L.x - ox, L.y - oy
            inten = L.intensity
            if L.flicker > 0:
                inten *= 1.0 + L.flicker * math.sin(ticks * L.flicker_speed + L._phase)
            self._emit(backend, lx, ly, L.radius, L.color, inten, w, h)

        backend.end_light_pass()
        backend.composite_lights()

    @staticmethod
    def _emit(backend, x, y, radius, color, intensity, w, h):
        if radius <= 0 or intensity <= 0:
            return
        # cull lights whose bounding box is fully off-screen
        if x + radius < 0 or x - radius > w or y + radius < 0 or y - radius > h:
            return
        backend.draw_light((x, y), radius, (color[0] * intensity, color[1] * intensity, color[2] * intensity))
