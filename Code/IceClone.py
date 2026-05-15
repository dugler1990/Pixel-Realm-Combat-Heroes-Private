import pygame
from Trap import Trap
from Enemy import Enemy
from Interaction import InteractionContext

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
        # Logic to freeze enemies in place
        
        # affected_sprites = pygame.sprite.spritecollide(self, self.groups[0], False)
        for sprite in self.groups[0]:
        #     if isinstance(sprite, Enemy) and sprite.frozen == False:  # Assuming there's an Enemy class
        #         sprite.freeze()  # Assuming enemies have a freeze method
            if isinstance(sprite, Enemy) and not sprite.frozen:
                distance = pygame.math.Vector2(sprite.rect.center).distance_to(self.rect.center)
                if distance < self.radius+180:
                    sprite.freeze()
    

    def explode(self):
        # Explosion effect, potentially dealing damage
        affected_sprites = pygame.sprite.spritecollide(self, self.groups[0], False, pygame.sprite.collide_circle)
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
