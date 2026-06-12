import random
import math
from dataclasses import dataclass

from Settings import DAY_LENGTH_SECONDS, WEATHER_DEFAULT_CLIMATE


@dataclass(frozen=True)
class Climate:
    """A weather baseline a level can adopt, and the target type for game triggers
    (e.g. weather.set_climate(CLIMATES['snowy_cold'])). Durations are in real seconds."""
    name: str = "temperate"
    allowed_precip: tuple = ("rain", "snow")   # () => never precipitates
    precip_chance: float = 0.45                # odds a clear spell turns to precipitation
    clear_duration_s: tuple = (40.0, 90.0)
    precip_duration_s: tuple = (20.0, 50.0)
    heavy_chance: float = 0.3                  # odds a precip spell is intensity 2 (heavy)
    snow_below_temp: float = 0.0               # snow (not rain) when temperature < this (°C)
    temp_day: float = 14.0                     # rough warmest temperature (~14:00)
    temp_night: float = 4.0                    # rough coldest temperature (~02:00)
    wind_base: float = 1.0                     # baseline wind intensity
    wind_gust: float = 1.5                     # extra wind per precip-intensity during spells


CLIMATES = {
    "temperate": Climate(),
    "snowy_cold": Climate(
        name="snowy_cold", allowed_precip=("snow",), precip_chance=0.7,
        clear_duration_s=(20.0, 50.0), precip_duration_s=(40.0, 90.0),
        snow_below_temp=2.0, temp_day=-2.0, temp_night=-10.0, wind_base=1.2,
    ),
    "clear": Climate(
        name="clear", allowed_precip=(), precip_chance=0.0,
        clear_duration_s=(60.0, 60.0), temp_day=20.0, temp_night=10.0, wind_base=0.6,
    ),
    "stormy": Climate(
        name="stormy", allowed_precip=("rain", "snow"), precip_chance=0.85,
        clear_duration_s=(15.0, 35.0), precip_duration_s=(40.0, 100.0),
        heavy_chance=0.7, temp_day=10.0, temp_night=3.0, wind_base=1.8, wind_gust=2.5,
    ),
}


def climate_by_name(name):
    """Resolve a climate (Climate, name string, or None) to a Climate, defaulting to
    the Settings default when unknown/None. Safe seam for level-authored climates."""
    if isinstance(name, Climate):
        return name
    return CLIMATES.get(name or WEATHER_DEFAULT_CLIMATE, CLIMATES[WEATHER_DEFAULT_CLIMATE])


class Weather:
    """Autonomous, configurable weather + time-of-day controller.

    Public attributes (read by WeatherOverlay/DaytimeBrightnessOverlay/AnimatedEnvironmentSprite/
    YSortCameraGroup.custom_draw) are kept stable: weather_type, weather_intensity,
    wind_direction, wind_intensity, current_time, light_level, temperature,
    time_speed_multiplier, day_length. Game logic drives it via set_climate()/force_weather().
    """

    MIN_LIGHT = 0.22  # matches DaytimeBrightnessOverlay.min_brightness so they agree

    def __init__(self, climate=None):
        self.climate = climate_by_name(climate)
        self.day_length = 24
        self.current_time = random.uniform(0, 24)   # hours [0, 24)
        self.time_speed_multiplier = 1.0

        # public state consumed elsewhere — start clear
        self.weather_type = 'clear'
        self.weather_intensity = 1                  # 1 = mild, 2 = heavy (overlay frame set)
        self.wind_direction = random.uniform(0, 360)
        self.wind_intensity = self.climate.wind_base
        self.temperature = self.climate.temp_day
        self.light_level = 1.0

        # internal spell timing
        self._spell_timer = random.uniform(*self.climate.clear_duration_s)

    # ---- public API for levels / game logic --------------------------------
    def set_climate(self, climate):
        """Adopt a new baseline climate (next spell decision uses it). Accepts a
        Climate, a name string, or None (-> default)."""
        self.climate = climate_by_name(climate)

    def force_weather(self, weather_type, intensity=None, duration_s=None):
        """Immediately set weather ('clear'|'rain'|'snow'); it holds for duration_s
        (or a climate-typical duration) before the autonomous cycle resumes."""
        wt = weather_type if weather_type in ('clear', 'rain', 'snow') else 'clear'
        self.weather_type = wt
        if wt == 'clear':
            self.weather_intensity = 1
            default_dur = random.uniform(*self.climate.clear_duration_s)
        else:
            self.weather_intensity = max(1, int(intensity)) if intensity else 2
            default_dur = random.uniform(*self.climate.precip_duration_s)
        self._spell_timer = default_dur if duration_s is None else duration_s

    # ---- per-frame update --------------------------------------------------
    def update(self, dt):
        self._advance_time(dt)
        self._update_temperature()
        self._update_light_level()
        self._update_wind(dt)
        self._update_precipitation(dt)

    def _advance_time(self, dt):
        hours_per_second = 24.0 / max(1e-6, DAY_LENGTH_SECONDS)
        self.current_time = (
            self.current_time + dt * hours_per_second * self.time_speed_multiplier
        ) % self.day_length

    def _update_temperature(self):
        # Smooth diurnal curve: warmest ~14:00, coldest ~02:00.
        c = self.climate
        phase = math.cos((self.current_time - 14.0) / 24.0 * 2 * math.pi)  # +1 @14h, -1 @02h
        self.temperature = (c.temp_day + c.temp_night) / 2 + (c.temp_day - c.temp_night) / 2 * phase

    def _update_light_level(self):
        # Same shape as DaytimeBrightnessOverlay.calculate_brightness so screen + (future)
        # per-sprite lighting agree.
        t = self.current_time
        lo = self.MIN_LIGHT
        if 12 <= t < 18:
            self.light_level = 1.0
        elif 18 <= t < 24:
            self.light_level = max(lo, 1.0 - (t - 18) / 6 * (1.0 - lo))
        elif 0 <= t < 6:
            self.light_level = lo
        else:  # 6 <= t < 12
            self.light_level = min(1.0, lo + (t - 6) / 6 * (1.0 - lo))

    def _update_wind(self, dt):
        # Slow directional drift; intensity eases toward a target that's higher during precip.
        self.wind_direction = (self.wind_direction + random.uniform(-30, 30) * dt) % 360
        precip = self.weather_type in ('rain', 'snow')
        target = self.climate.wind_base + (self.climate.wind_gust * self.weather_intensity if precip else 0.0)
        self.wind_intensity += (target - self.wind_intensity) * min(1.0, 2.0 * dt)
        self.wind_intensity = max(0.0, self.wind_intensity + random.uniform(-0.3, 0.3) * dt)

    def _update_precipitation(self, dt):
        self._spell_timer -= dt
        if self._spell_timer > 0:
            return
        self._choose_next_weather()

    def _choose_next_weather(self):
        c = self.climate
        if self.weather_type == 'clear':
            if c.allowed_precip and random.random() < c.precip_chance:
                wants_snow = self.temperature < c.snow_below_temp
                if wants_snow and 'snow' in c.allowed_precip:
                    self.weather_type = 'snow'
                elif 'rain' in c.allowed_precip:
                    self.weather_type = 'rain'
                else:
                    self.weather_type = c.allowed_precip[0]
                self.weather_intensity = 2 if random.random() < c.heavy_chance else 1
                self._spell_timer = random.uniform(*c.precip_duration_s)
            else:
                self.weather_type = 'clear'
                self.weather_intensity = 1
                self._spell_timer = random.uniform(*c.clear_duration_s)
        else:
            # precip spell ended -> return to clear
            self.weather_type = 'clear'
            self.weather_intensity = 1
            self._spell_timer = random.uniform(*c.clear_duration_s)

    def calculate_wind_force(self):
        rad = math.radians(self.wind_direction)
        return self.wind_intensity * math.cos(rad), self.wind_intensity * math.sin(rad)
