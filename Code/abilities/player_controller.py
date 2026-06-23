"""Dispatch player input to weapon / magic / evasion abilities."""

from __future__ import annotations

import pygame

from abilities.protocol import PlayerAbilityContext
from Settings import magic_data, weapon_data


class PlayerActionController:
    def __init__(
        self,
        player,
        weapon_ability,
        magic_ability,
        evasion_abilities,
        evasion_order,
        destroy_attack,
    ):
        self.player = player
        self.weapon_ability = weapon_ability
        self.magic_ability = magic_ability
        self.evasion_abilities = evasion_abilities
        self.evasion_order = list(evasion_order)
        self.destroy_attack = destroy_attack

    def _context(self):
        return PlayerAbilityContext.from_player(self.player)

    def _current_evasion_ability(self, player):
        ability_id = self.evasion_order[player.current_evasion_index]
        return self.evasion_abilities[ability_id]

    def get_active_tickable(self):
        for ability in self.evasion_abilities.values():
            if ability.is_active(self.player) and hasattr(ability, "tick"):
                return ability
        return None

    def allows_air_steering(self, player) -> bool:
        runtime = getattr(player, "_leap_runtime", None)
        return runtime is not None and runtime.get("phase") == "airborne"

    def is_movement_locked(self, player) -> bool:
        if getattr(player, "_dash_runtime", None) is not None:
            return True
        if self.allows_air_steering(player):
            return False
        if getattr(player, "_leap_runtime", None) is not None:
            return True
        active = self.get_active_tickable()
        if active is not None and active.suppresses_locomotion(player):
            return True
        return False

    def is_input_locked(self, player) -> bool:
        if getattr(player, "_leap_runtime", None) is not None:
            return True
        if getattr(player, "_dash_runtime", None) is not None:
            return True
        if getattr(player, "_charge_runtime", None) is not None:
            return True
        if player.status.startswith("sit_") or player.seated_object is not None:
            return True
        return False

    def suppresses_locomotion(self, player) -> bool:
        active = self.get_active_tickable()
        if active is not None:
            return active.suppresses_locomotion(player)
        return False

    def tick(self, player, dt, QuadTree, entity_quad_tree) -> None:
        active = self.get_active_tickable()
        if active is None:
            return
        active.tick(player, self._context(), dt, QuadTree, entity_quad_tree)

    def get_charge_ratio(self, player) -> float:
        active = self._current_evasion_ability(player)
        if hasattr(active, "charge_ratio"):
            return active.charge_ratio(player)
        runtime = getattr(player, "_charge_runtime", None)
        if runtime is not None:
            return float(runtime.get("charge_ratio", 0.0))
        return 0.0

    def try_use_slot(self, player, slot_name, **kwargs) -> bool:
        if slot_name == "weapon":
            return self.weapon_ability.try_start(player, self._context(), **kwargs)
        if slot_name == "magic":
            return self.magic_ability.try_start(player, self._context(), **kwargs)
        if slot_name == "evasion":
            ability_id = self.evasion_order[player.current_evasion_index]
            ability = self.evasion_abilities[ability_id]
            return ability.try_start(player, self._context(), **kwargs)
        raise ValueError(f"unknown slot {slot_name!r}")

    def handle_input(self, player, input_manager) -> None:
        current_time = pygame.time.get_ticks()
        ctx = self._context()
        evasion_ability = self._current_evasion_ability(player)

        if hasattr(evasion_ability, "on_release"):
            if input_manager.previous_key_states.get(pygame.K_c, False) and not input_manager.is_key_pressed(pygame.K_c):
                evasion_ability.on_release(player, ctx)
                return

        if self.is_input_locked(player):
            return

        if player.attacking:
            return

        if not player.inventory.visible and player.has_belt and player.belt_capacity > 0:
            belt_keys = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4)
            for i, key in enumerate(belt_keys):
                if input_manager.is_key_just_pressed(key) and i < player.belt_capacity:
                    player.use_belt_slot(i)

        if input_manager.is_key_just_pressed(pygame.K_i):
            if current_time - player.last_i_press_time > 500:
                player.level.toggle_inventory()
                player.last_i_press_time = current_time

        if input_manager.is_key_pressed(pygame.K_LALT) or input_manager.is_key_pressed(pygame.K_RALT):
            if input_manager.is_key_just_pressed(pygame.K_q):
                if current_time - player.last_q_press_time > 500:
                    player.level.toggle_attack_selection()
                    player.last_q_press_time = current_time

        if input_manager.is_key_pressed(pygame.K_SPACE):
            self.try_use_slot(player, "weapon")

        if input_manager.is_key_pressed(pygame.K_LCTRL):
            self.try_use_slot(player, "magic")

        if input_manager.is_key_pressed(pygame.K_q) and player.can_switch_weapon:
            player.can_switch_weapon = False
            player.weapon_switch_time = pygame.time.get_ticks()
            if player.weapon_index < len(list(weapon_data.keys())) - 1:
                player.weapon_index += 1
            else:
                player.weapon_index = 0
            player.weapon = list(weapon_data.keys())[player.weapon_index]

        if input_manager.is_key_pressed(pygame.K_e) and player.can_switch_magic:
            player.can_switch_magic = False
            player.magic_switch_time = pygame.time.get_ticks()
            if player.magic_index < len(list(magic_data.keys())) - 1:
                player.magic_index += 1
            else:
                player.magic_index = 0
            player.magic = list(magic_data.keys())[player.magic_index]

        if input_manager.is_key_just_pressed(pygame.K_r) and player.can_switch_evasion:
            player.can_switch_evasion = False
            player.evasion_switch_time = current_time
            player.current_evasion_index = (player.current_evasion_index + 1) % len(self.evasion_order)

        if input_manager.is_key_just_pressed(pygame.K_c):
            direction = player.get_direction_as_string()
            if hasattr(evasion_ability, "on_press"):
                evasion_ability.on_press(player, ctx, direction=direction)
            else:
                self.try_use_slot(player, "evasion", direction=direction)

        if input_manager.is_key_just_pressed(pygame.K_p):
            if current_time - player.last_p_press_time > 500:
                player.level.toggle_menu()
                player.last_p_press_time = current_time
