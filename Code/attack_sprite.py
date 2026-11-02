"""What every attack sprite carries: the one contract the hit loop reads.

Weapon and ParticleEffect are the only sprites in Level4's attack_sprites and
enemy_attack_sprites groups. Each calls init_attack() in its __init__, and
Level4._strike_with_attack_sprites reads these fields directly, so a sprite that skips
init_attack fails loudly (AttributeError) instead of quietly hitting with defaults.
"""


class AttackSprite:
    """Mixin for sprites that hit things. Call init_attack() in __init__."""

    def init_attack(self, *, owner, source_team, source_kind, attack_type,
                    amount=None, tags=(), rehit_ms=None, stops=False):
        self.owner = owner
        self.source_team = source_team
        self.source_kind = source_kind
        self.attack_type = attack_type
        self.interaction_kind = "damage"
        self.amount = amount
        self.tags = set(tags)
        # Repeat rule (InteractionResolver.strike): when this attack last hit each body,
        # and how long before it may hit the same body again (None = once per attack).
        self.hits = {}
        self.rehit_ms = rehit_ms
        # Stops at the first body it lands on (arrows, stones); the sprite defines stop().
        self.stops = stops
