import pygame
from IceClone import IceClone


class EvasionPlayer:
    """Legacy helper; ice clone spawning moved to abilities.instant.InstantEvasionAbility."""

    def __init__(self, animation_player, create_trap_callback):
        self.animation_player = animation_player
        self.create_trap = create_trap_callback

    def create_ice_clone(self, player, effect_type='freeze', lifespan=3000, radius=5):
        if player.energy >= 2:
            player.energy -= 2
            trap_config = {
                'class': IceClone,
                'pos': player.rect.center,
                'groups': player.groups(),
                'image_path': '../Graphics/Traps/Ice/ice_clone.png',
                'effect_type': effect_type,
                'trigger':'proximity',
                'death_animation':'ice_clone_death_1',
                'lifespan': lifespan,
                'radius': radius,
                'health': 100,
                'exp_value': 50,
                'owner': player,
                'source_team': getattr(player, "team_id", "player"),
                'source_kind': "special",
                'attack_type': effect_type,
                'amount': None,
                'tags': {"summon", "special"},
            }
            self.create_trap(trap_config)
