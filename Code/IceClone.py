from Trap import Trap
from combat_unit import CombatUnit
from Interaction import InteractionContext
import hit_core
from Settings import VIEW_ELEVATION_DEG

class IceClone(Trap):
    def __init__(self, pos, groups, image_path, animation_player, effect_type,
                 death_animation, add_exp, target_type="enemies", trigger="timer", lifespan=3000, radius=0, health=100, exp_value=0):
        super().__init__(pos, groups, image_path, animation_player, effect_type, death_animation, add_exp,
                         target_type=target_type, trigger=trigger, lifespan=lifespan, radius=radius, health=health, exp_value=exp_value)
        # IceClone specific initialization can go here

    def activate(self):
        # Custom activation logic for IceClones
        super().activate()  # Call the base class activate to handle particle effects
        # Additional IceClone specific effects can be handled here

        # Example: Handling different types of ice clone effects
        if self.effect_type == "freeze":
            self.freeze_enemies()
        elif self.effect_type == "explode":
            self.explode()

    def freeze_enemies(self):
        """Freeze every unit whose feet the freeze circle (radius + 180) touches."""
        blast = hit_core.ground_disc(self.rect.midbottom, self.radius + 180, VIEW_ELEVATION_DEG)
        for sprite in hit_core.find_hits(
            blast, self.groups[0], exclude=(self,), body=hit_core.foot_shape
        ):
            if isinstance(sprite, CombatUnit) and not sprite.frozen:
                sprite.freeze()

    def explode(self):
        # Explosion effect, potentially dealing damage
        blast = hit_core.ground_disc(self.rect.midbottom, self.radius, VIEW_ELEVATION_DEG)
        affected_sprites = hit_core.find_hits(
            blast, self.groups[0], exclude=(self,), body=hit_core.foot_shape
        )
        for sprite in affected_sprites:
            ctx = InteractionContext(
                kind="damage",
                source_kind=getattr(self, "source_kind", "special"),
                source=getattr(self, "owner", self),
                owner=getattr(self, "owner", None),
                source_team=getattr(self, "source_team", None)
                or getattr(getattr(self, "owner", None), "team_id", "neutral"),
                target=sprite,
                amount=getattr(self, "amount", 50) or 50,
                attack_type=getattr(self, "attack_type", "explosion"),
                tags=set(getattr(self, "tags", {"special"})),
            )
            resolver = None
            if hasattr(self, "owner") and self.owner is not None:
                owner_level = getattr(self.owner, "level", None)
                if owner_level is not None and hasattr(owner_level, "interaction_resolver"):
                    resolver = owner_level.interaction_resolver
            if resolver is not None:
                resolver.apply(ctx)
            elif hasattr(sprite, "receive_interaction"):
                if hasattr(sprite, "can_receive_interaction"):
                    if sprite.can_receive_interaction(ctx):
                        sprite.receive_interaction(ctx)
                else:
                    sprite.receive_interaction(ctx)
