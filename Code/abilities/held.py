"""Held / instant player actions for weapon and magic slots."""

from __future__ import annotations

from abilities.base import PlayerAbility
from Settings import magic_data, weapon_data


class HeldWeaponAbility(PlayerAbility):
    ability_id = "weapon"

    def __init__(self, create_attack, attack_sound):
        self.create_attack = create_attack
        self.attack_sound = attack_sound

    def try_start(self, entity, context, **kwargs) -> bool:
        import pygame

        entity.attacking = True
        entity.attack_time = pygame.time.get_ticks()
        self.create_attack()
        if self.attack_sound is not None:
            self.attack_sound.play()
        return True

    def suppresses_locomotion(self, entity) -> bool:
        return False


class HeldMagicAbility(PlayerAbility):
    ability_id = "magic"

    def __init__(self, create_magic):
        self.create_magic = create_magic

    def try_start(self, entity, context, **kwargs) -> bool:
        import pygame

        entity.attacking = True
        entity.attack_time = pygame.time.get_ticks()
        style = list(magic_data.keys())[entity.magic_index]
        strength = list(magic_data.values())[entity.magic_index]["strength"] + entity.stats["magic"]
        cost = list(magic_data.values())[entity.magic_index]["cost"]
        self.create_magic(style, strength, cost)
        return True

    def suppresses_locomotion(self, entity) -> bool:
        return False
