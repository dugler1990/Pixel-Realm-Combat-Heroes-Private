# Import DEFAULT_FRICTION from Entity to keep friction values aligned
try:
    from Entity import DEFAULT_FRICTION
except ImportError:
    # Fallback if import fails (shouldn't happen in normal use)
    DEFAULT_FRICTION = 0.5

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
        """Return friction multiplier (higher = less friction loss, more slippery)
        Uses DEFAULT_FRICTION from Entity to keep values aligned
        """
        return DEFAULT_FRICTION  # Use same default as Entity
    
    def should_persist_after_exit(self):
        """Return True if effect should persist after leaving effect area"""
        return False


class SlipperyEffect(Effect):
    """
    Slippery effect that adds inertia to movement.
    Higher slippery_factor = less friction (more slippery), less acceleration (harder to change direction).
    """
    def __init__(self, properties):
        super().__init__(properties)
        self.slippery_factor = properties.get('slippery_factor', 1.0)
        
        # Convert slippery_factor to acceleration and friction multipliers
        # Higher factor = less friction (more slippery), LESS acceleration (harder to change direction)
        # Factor of 50 means very slippery (low friction), but also very hard to change direction
        
        # For friction: higher factor -> higher multiplier (less friction loss, more slippery)
        # Formula: start at DEFAULT_FRICTION (normal), approach 0.99 (very slippery) as factor increases
        base_friction = DEFAULT_FRICTION  # Use same base as Entity
        max_slippery = 0.99  # Maximum slippery (1% velocity loss per frame)
        friction_boost = (max_slippery - base_friction) * min(self.slippery_factor / 50.0, 1.0)
        self.friction_multiplier = base_friction + friction_boost
        
        # For acceleration: higher slippery_factor -> LOWER multiplier (harder to accelerate/change direction)
        # Start at 1.0 (normal), decrease to ~0.3 (very slippery = hard to change direction)
        min_acceleration = 0.3  # Minimum acceleration multiplier (very hard to change direction)
        acceleration_reduction = (1.0 - min_acceleration) * min(self.slippery_factor / 50.0, 1.0)
        self.acceleration_multiplier = 1.0 - acceleration_reduction
    
    def get_acceleration_multiplier(self):
        return self.acceleration_multiplier
    
    def get_friction_multiplier(self):
        return self.friction_multiplier
    
    def should_persist_after_exit(self):
        """Slippery effect stops immediately when leaving"""
        return False


# Effect Registry: Maps property keys to Effect classes
EFFECT_REGISTRY = {
    'slippery_factor': SlipperyEffect,
}

