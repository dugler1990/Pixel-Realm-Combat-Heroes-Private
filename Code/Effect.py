# Import DEFAULT_FRICTION from Entity to keep friction values aligned
import math

try:
    from Entity import DEFAULT_FRICTION
except ImportError:
    # Fallback if import fails (shouldn't happen in normal use)
    DEFAULT_FRICTION = 0.5

from game_logging import get_debug_logger

_effect_env_log = get_debug_logger("effect_environmental")

# slippery_factor is log-mapped to s in [0, 1] between _SLIP_F_MIN and _SLIP_F_MAX.
# *_MIN / *_MAX below = output when slippery_factor is at that end of the range (see _SLIP_F_MIN / _SLIP_F_MAX).
_SLIP_F_MIN = 0.1
_SLIP_F_MAX = 50.0
_SLIP_FRIC_MIN = 0.2   # friction_mult at slippery_factor == _SLIP_F_MIN
_SLIP_FRIC_MAX = 0.99  # friction_mult at slippery_factor == _SLIP_F_MAX
_SLIP_ACC_MIN = 0.48   # acceleration_mult at slippery_factor == _SLIP_F_MIN
_SLIP_ACC_MAX = 0.3    # acceleration_mult at slippery_factor == _SLIP_F_MAX (can be < _SLIP_ACC_MIN)


def _slippery_normalized_s(f: float) -> float:
    """Map slippery_factor to [0,1] using log space between _SLIP_F_MIN and _SLIP_F_MAX."""
    if f <= _SLIP_F_MIN:
        return 0.0
    if f >= _SLIP_F_MAX:
        return 1.0
    log_lo = math.log(_SLIP_F_MIN)
    log_hi = math.log(_SLIP_F_MAX)
    return (math.log(f) - log_lo) / (log_hi - log_lo)


class Effect:
    """
    Base class for all effects.
    Effects modify entity behavior while active.
    """
    def __init__(self, properties):
        self.properties = properties
    
    def apply(self, entity):
        """Called when effect is first applied to entity"""
        pass
    
    def remove(self, entity):
        """Called when effect is removed from entity"""
        pass
    
    def get_acceleration_multiplier(self):
        """Return acceleration multiplier (1.0 = normal)"""
        return 1.0
    
    def get_friction_multiplier(self):
        """Absolute friction mult for velocity when no input (higher = more slide).
        Entity.move averages this across active effects.
        Return DEFAULT_FRICTION for neutral.
        """
        return DEFAULT_FRICTION  # Use same default as Entity
    
    def should_persist_after_exit(self):
        """Return True if effect should persist after leaving effect area"""
        return False

    def get_environmental_damage(self, entity, dt):
        """Return (amount, damage_type) for damage this frame, or None. Override in damage effects."""
        return None


class SlipperyEffect(Effect):
    """
    One Tiled property ``slippery_factor`` maps to blend s in [0,1] (log scale on
    [_SLIP_F_MIN, _SLIP_F_MAX]). Same s drives two linear outputs:

    - friction_multiplier: lerp between _SLIP_FRIC_MIN and _SLIP_FRIC_MAX
    - acceleration_multiplier: lerp between _SLIP_ACC_MIN and _SLIP_ACC_MAX

    ``f <= 0`` is neutral (DEFAULT_FRICTION, accel 1.0).

    Entity.move averages friction across effects, uses min for accel, and maps
    accel into separate parallel/perpendicular input response gains for drift control.
    """
    def __init__(self, properties):
        super().__init__(properties)
        raw = properties.get('slippery_factor', _SLIP_F_MIN)
        try:
            f = float(raw)
        except (TypeError, ValueError):
            f = _SLIP_F_MIN
        self.slippery_factor = f

        if f <= 0:
            self.friction_multiplier = DEFAULT_FRICTION
            self.acceleration_multiplier = 1.0
        else:
            s = _slippery_normalized_s(f)
            self.friction_multiplier = _SLIP_FRIC_MIN + (_SLIP_FRIC_MAX - _SLIP_FRIC_MIN) * s
            self.acceleration_multiplier = _SLIP_ACC_MIN + (_SLIP_ACC_MAX - _SLIP_ACC_MIN) * s
    
    def get_acceleration_multiplier(self):
        return self.acceleration_multiplier
    
    def get_friction_multiplier(self):
        return self.friction_multiplier
    
    def should_persist_after_exit(self):
        """Slippery effect stops immediately when leaving"""
        return False


class HeatEffect(Effect):
    """Heat while you stand in it: (heat − fire resist) × (1 − insulation) per second, from the
    chest's outer layer. The entity's fire_resistance is not read. Leaving starts a hot shell
    when one second of that heat is above COOK."""

    def __init__(self, properties):
        super().__init__(properties)
        self.heat = float(properties.get('heat', 0))

    def get_environmental_damage(self, entity, dt):
        _effect_env_log.debug("trying to get environmental damage")
        from damage_rules import patch_rate
        amount = patch_rate(entity, self.heat) * dt
        if amount <= 0:
            return None
        return (amount, 'heat')

    def remove(self, entity):
        from damage_rules import COOK, chest_layer, heat_seconds, heat_shade, patch_rate
        held = patch_rate(entity, self.heat)
        if held <= COOK:
            return
        from hit_resolve import _clock, remember_heat
        remember_heat(entity, chest_layer(entity), heat_shade(held))
        clock = _clock(entity)
        if clock is None:
            return
        try:
            import pygame
            now = pygame.time.get_ticks()
        except Exception:
            import time
            now = int(time.time() * 1000)
        clock.start(entity, "hot_shell", now, duration_ms=int(round(heat_seconds(held) * 1000)))


# Effect Registry: Maps property keys to Effect classes
EFFECT_REGISTRY = {
    'slippery_factor': SlipperyEffect,
    'heat': HeatEffect,
}
