import pygame
from Support import import_folder, position_surface_mask_midbottom_at
from Settings import *
from game_logging import get_debug_logger
from Entity import Entity

_player_item_log = get_debug_logger("player_item")
_combat_log = get_debug_logger("combat")
import os
from Inventory import Inventory
from PlayerConfiguration import PlayerConfiguration
from inputManager import InputManager
from AttackSelection import AttackSelection
from Settings import *
from Support import frames_to_masks
from Interaction import InteractionContext
from abilities.registry import build_action_controller, load_evasion_loadout

class BasePlayer(Entity):
    # Bare direction names are the walk cycles; every other status ("_idle", "_attack",
    # "sit_*", "jump_*", "land_*", "leap_*") is not locomotion and stays time-based.
    WALK_STATUSES = frozenset({"up", "down", "left", "right"})

    def __init__(self,
                 pos,
                 groups,
                 obstacle_sprites,
                 create_attack,
                 destroy_attack,
                 create_magic,
                 create_trap,
                 initial_stats,
                 level,
                 input_manager,
                 character_assets,
                 QuadTree,
                 entity_quad_tree,
                 layout_callback_update_quad_tree = None):
        
        super().__init__(groups,layout_callback_update_quad_tree)
        
        #self.TILESIZE = TILESIZE * 0.4# hardcoded bs fix it.
        self.type = 'player'
        # Set once in __init__ so update()/recovery never hit AttributeError (e.g. threaded sprite updates).
        self.is_dead = False
        self.previous_tile = None
        self.power_level = 1
        self.inventory = Inventory(self, input_manager)
        
        self.level = level
        self.input_manager = input_manager
        self.last_p_press_time = 0
        self.last_i_press_time = 0
        self.last_q_press_time = 0
        # Graphics Setup
        self.import_player_assets(character_assets)
        self.status = "down"
        self.masks = self.convert_animations_to_masks(self.animations)
        # Movement
        self.attacking = False
        self.attack_cooldown = 400
        self.attack_time = None

        self.obstacle_sprites = obstacle_sprites
        self.QuadTree = QuadTree
        # Weapon
        self.create_attack = create_attack
        self.destroy_attack = destroy_attack
        self.weapon_index = 0
        self.weapon = list(weapon_data.keys())[self.weapon_index]
        self.can_switch_weapon = True
        self.weapon_switch_time = None
        self.switch_duration_cooldown = 200

        # Magic
        self.magic_available = magic_data
        self.create_magic = create_magic
        self.magic_index = 0
        self.magic = list(magic_data.keys())[self.magic_index]
        self.can_switch_magic = True
        self.magic_switch_time = None

        self.attack_selection = AttackSelection(self, input_manager)
        self.seated_object = None
        self.seat_anchor_world = None
        self.seat_player_offset = (0, 0)
        self.post_seat_status = "down_idle"


        # Evasions / player action dispatch
        self.evasion_types = load_evasion_loadout(character_assets)
        self.create_trap = create_trap
        self._dash_runtime = None
        self._charge_runtime = None
        self._leap_runtime = None
        self.character_assets = character_assets
        self.can_switch_evasion = True
        self.evasion_switch_time = None
        self.switch_evasion_cooldown = 200
        # Stats    BAS ARE IN /Graphics/PlayerSelectionDict.json
        # self.base_stats = {"health": 1000,
        #                     "energy": 60,
        #                     "attack": 10,
        #                     "magic": 4,
        #                     "speed": 10, 
        #                     "strength": 5,
        #                     "intelligence":7,
        #                     "agility":6,
        #                     "charisma":3}
        
        
        
        self.stats  = initial_stats 
        self.player_config = PlayerConfiguration( input_manager = input_manager,
                                                  base_stats = self.stats,
                                                  remaining_points=2)   
        
        
        ## WL 
        # I need to set new magic , new energy, new health, there should be health recovery too.
        
        ### New neregy value, but magic need to be accounted for too, magic is jsut mana regen , right ? 
        
        #   I should add health regen here, add vitality.
        
        # 
        
        
        
        
        self.max_stats = {"health": 300, "energy": 140, "attack": 20, "magic": 10, "speed": 10}
        self.upgrade_cost = {"health": 100, "energy": 100, "attack": 100, "magic": 100, "speed": 100}
        # Upgrade UI must match max_stats / upgrade_cost keys (not len(self.stats), which may include vitality etc.)
        self.upgrade_stat_order = tuple(self.max_stats.keys())
        self.health = self.stats["health"]
        self.energy = self.stats["energy"]
        self.exp = 0
        self.gold = 0
        self.has_belt = False
        self.belt_capacity = 0
        self.speed = self.stats["speed"]
        self.speed_multiplier = 1 
        
        # Damage Timer
        self.vulnerable = True
        self.hurt_time = None
        self.invulnerability_duration = 0

        # Import Sound
        self.weapon_attack_sound = pygame.mixer.Sound("../Audio/Sword.wav")
        self.weapon_attack_sound.set_volume(0.2)

        self.action_controller = build_action_controller(
            self,
            create_attack,
            destroy_attack,
            create_magic,
            create_trap,
            self.weapon_attack_sound,
            evasion_loadout=load_evasion_loadout(character_assets),
        )
        self.current_evasion_index = 0

        self.scale_animation()
        self.team_id = "player"
        
        
    

    def get_damage(self, amount, attack_type=None):
        if self.vulnerable:
            self.health -= amount
            self.vulnerable = False
            self.hurt_time = pygame.time.get_ticks()
            
            if attack_type:
                if attack_type != 'melee': ## TODO : a at the moment this is recieving attack type to do attack particles, 
                                                    # we do not have any attack particles for this so screw it.
                    # LayoutManager is passed as obstacle_sprites; animation_player lives on level
                    animation_player = getattr(self.level, "animation_player", None)
                    if animation_player is not None and attack_type in getattr(animation_player, "frames", {}):
                        animation_player.create_particles(
                            attack_type, self.rect.center, [self.obstacle_sprites.visible_sprites]
                        )

    def can_receive_interaction(self, ctx: InteractionContext):
        if ctx.kind == "effect_state":
            return True
        if ctx.kind == "impulse":
            if "friendly_fire_impulse" in ctx.tags:
                return True
            if ctx.source_team == self.team_id:
                return False
            return True
        if ctx.kind != "damage":
            return False
        if ctx.source_team == self.team_id:
            return False
        return True

    def receive_interaction(self, ctx: InteractionContext):
        if ctx.kind == "impulse":
            force = pygame.math.Vector2(ctx.impulse_x or 0, ctx.impulse_y or 0)
            follow_through = 0.5
            if ctx.source is not None:
                follow_through = float(getattr(ctx.source, "impulse_follow_through", 0.5))
            self.apply_impulse(force, follow_through=follow_through)
            return
        if ctx.kind == "effect_state":
            super().receive_interaction(ctx)
            return
        if ctx.kind != "damage":
            return
        amount = ctx.amount
        if amount is None:
            source = ctx.source
            if source is not None and hasattr(source, "get_full_weapon_damage") and hasattr(source, "get_full_magic_damage"):
                if ctx.attack_type == "weapon":
                    amount = source.get_full_weapon_damage()
                else:
                    amount = source.get_full_magic_damage()
        if amount is None:
            return
        health_before = self.health
        if ctx.source_kind == "environment":
            self.take_environmental_damage(amount, ctx.attack_type)
            _combat_log.debug(
                "player_damage_ingress source_kind=%r source_team=%r amount=%r attack_type=%r health_before=%r health_after=%r",
                ctx.source_kind,
                ctx.source_team,
                amount,
                ctx.attack_type,
                health_before,
                self.health,
            )
            return
        self.get_damage(amount, ctx.attack_type)
        _combat_log.debug(
            "player_damage_ingress source_kind=%r source_team=%r amount=%r attack_type=%r health_before=%r health_after=%r",
            ctx.source_kind,
            ctx.source_team,
            amount,
            ctx.attack_type,
            health_before,
            self.health,
        )

    def take_environmental_damage(self, amount, damage_type):
        """Apply environmental damage (e.g. heat); reuses vulnerability via get_damage. No attack_type so particle branch is skipped until environmental types are defined."""
        self.get_damage(amount, None)

    # def get_damage(self, player, attack_type):
    #     if self.vulnerable:
    #         self.hit_sound.play()
    #         self.direction = self.get_player_distance_direction(player)[1]
    #         if attack_type == "weapon":
    #             self.health -= player.get_full_weapon_damage()
    #         else:
    #             self.health -= player.get_full_magic_damage()
    #         self.hit_time = pygame.time.get_ticks()
            

    def scale_animation(self):
        if hasattr(self, "TILESIZE"):
            for state, frames in self.animations.items():
                for i, frame in enumerate(frames):
                    self.animations[state][i] = pygame.transform.scale(frame, (self.TILESIZE, self.TILESIZE))


    def import_player_assets(self, character_path):
        #print("\n\n attempt at import \n\n")
        #print(character_path)
        self.animations = {
            "up": [], "down": [], "left": [], "right": [],
            "right_idle": [], "left_idle": [], "up_idle": [], "down_idle": [],
            "right_attack": [], "left_attack": [], "up_attack": [], "down_attack": [],
            "slide_right":[],"slide_left":[],
            "leap_windup_right": [], "leap_windup_left": [],
            "leap_windup_up": [], "leap_windup_down": [],
            "jump_right": [], "jump_left": [],
            "jump_up": [], "jump_down": [],
            "land_right": [], "land_left": [],
            "land_up": [], "land_down": [],
            "sit_down": [], "sit_idle": [], "sit_up": []
        }

        for animation in self.animations.keys():
            full_path = character_path + animation
            self.animations[animation] = import_folder(full_path)
            
    def convert_animations_to_masks(self, animations_dict):
        masks = {}
        for key in animations_dict.keys():
            animation_set = animations_dict[key]
            mask_set = frames_to_masks(animation_set)
            masks.update( {key:mask_set} )
        return masks


    def update_derived_attributes(self):
        self.health = self.stats["health"]
        self.energy = self.stats["energy"]
        self.speed = self.stats["speed"]
        self.magic_power = self.stats["magic"]

    def set_speed_multiplier(self, multiplier):
        """Set the speed multiplier to temporarily adjust the player's speed."""
        self.speed_multiplier = multiplier
        
        
        
    def apply_item_effect(self, effect):
        """Apply consumable effect dict (e.g. health/mana from standard_items.json)."""
        if not effect:
            return
        if "health" in effect:
            cap = self.stats.get("health", self.health)
            self.health = min(self.health + effect["health"], cap)
        if "mana" in effect:
            cap = self.stats.get("energy", self.energy)
            self.energy = min(self.energy + effect["mana"], cap)

    def pickup_item(self, item):
        _player_item_log.debug("item.effect_type:%s", item.effect_type)
        if hasattr(self, "TILESIZE"):
            _player_item_log.debug("%s", self.TILESIZE)
        if getattr(item, "effect_type", None) == "gold":
            effect = getattr(item, "effect", None) or {}
            amt = int(effect.get("gold", 0))
            if amt <= 0:
                return False
            self.gold += amt
            if getattr(self, "level", None) is not None and hasattr(self.level, "notify_gold_pickup"):
                self.level.notify_gold_pickup(amt)
            return True
        return self.inventory.add_item(item)

    def can_pickup(self, item):
        """Non-mutating: would pickup_item() succeed? Gold always fits; other
        items need inventory room. Used by co-op to pre-check a shared pickup."""
        if getattr(item, "effect_type", None) == "gold":
            return True
        return self.inventory.has_room_for(item)

    def _apply_air_steering_input(self):
        if self.input_manager.is_key_pressed(pygame.K_LEFT):
            self.direction.x = -1
        elif self.input_manager.is_key_pressed(pygame.K_RIGHT):
            self.direction.x = 1
        else:
            self.direction.x = 0

        if self.input_manager.is_key_pressed(pygame.K_UP):
            self.direction.y = -1
        elif self.input_manager.is_key_pressed(pygame.K_DOWN):
            self.direction.y = 1
        else:
            self.direction.y = 0

    def _apply_movement_input(self):
        if self.action_controller.allows_air_steering(self):
            self._apply_air_steering_input()
            return
        if self.action_controller.is_movement_locked(self):
            return
        released_keys = [
            key
            for key in self.input_manager.previous_key_states
            if self.input_manager.previous_key_states[key]
            and not self.input_manager.current_key_states[key]
        ]
        for key in released_keys:
            if key == pygame.K_UP:
                self.direction.y = 0
            elif key == pygame.K_DOWN:
                self.direction.y = 0
            elif key == pygame.K_LEFT:
                self.direction.x = 0
            elif key == pygame.K_RIGHT:
                self.direction.x = 0

        if self.attacking:
            return

        if self.input_manager.is_key_pressed(pygame.K_UP):
            self.direction.y = -1
            self.status = "up"
        elif self.input_manager.is_key_pressed(pygame.K_DOWN):
            self.direction.y = 1
            self.status = "down"
        else:
            self.direction.y = 0

        if self.input_manager.is_key_pressed(pygame.K_RIGHT):
            self.direction.x = 1
            self.status = "right"
        elif self.input_manager.is_key_pressed(pygame.K_LEFT):
            self.direction.x = -1
            self.status = "left"
        else:
            self.direction.x = 0

    def input(self):
        interact_fn = getattr(self.level, "try_interact_nearby_environment", None)
        if interact_fn is None:
            interact_fn = getattr(self.level, "try_open_nearby_chest", None)
        if interact_fn and interact_fn():
            return
        if self.status.startswith("sit_") or self.seated_object is not None:
            self.attacking = False
            self.direction.x = 0
            self.direction.y = 0
            return

        self._apply_movement_input()
        self.action_controller.handle_input(self, self.input_manager)

    def get_direction_as_string(self):
        if getattr(self, "_charge_runtime", None) is not None:
            charge_dir = self._charge_runtime.get("direction")
            if charge_dir in ("left", "right", "up", "down"):
                return charge_dir

        dx = self.direction.x
        dy = self.direction.y
        if abs(dy) > abs(dx):
            if dy < 0:
                return "up"
            if dy > 0:
                return "down"
        if dx < 0:
            return "left"
        if dx > 0:
            return "right"

        base = self.status.split("_")[0]
        if base in ("up", "down", "left", "right"):
            return base
        return "right"


    def get_status(self):
        if self.status.startswith("sit_"):
            self.attacking = False
            self.direction.x = 0
            self.direction.y = 0
            return
        if getattr(self, "_dash_runtime", None) is not None:
            self.attacking = False
            self.direction.x = 0
            self.direction.y = 0
            return
        if getattr(self, "_charge_runtime", None) is not None:
            self.attacking = False
            return
        if getattr(self, "_leap_runtime", None) is not None:
            self.attacking = False
            if self._leap_runtime.get("phase") != "airborne":
                self.direction.x = 0
                self.direction.y = 0
            return
        if self.direction.x == 0 and self.direction.y == 0:
            if not "idle" in self.status and not "attack" in self.status:
                self.status += "_idle"
        else:
            if self.attacking:
                self.direction.x = 0
                self.direction.y = 0
                if not "attack" in self.status:
                    if "idle" in self.status:
                        self.status = self.status.replace("_idle", "_attack")
                    else:
                        self.status = self.status + "_attack"
            else:
                if "attack" in self.status:
                    self.status = self.status.replace("_attack", "")

    def cooldowns(self):
        current_time = pygame.time.get_ticks()
        if self.attacking:
            if current_time - self.attack_time >= self.attack_cooldown + weapon_data[self.weapon]["cooldown"]:
                self.attacking = False
                self.destroy_attack()
        if not self.can_switch_evasion:
            if current_time - self.evasion_switch_time >= self.switch_evasion_cooldown:
                self.can_switch_evasion = True
                
        if not self.can_switch_weapon:
            if current_time - self.weapon_switch_time >= self.switch_duration_cooldown:
                self.can_switch_weapon = True

        if not self.can_switch_magic:
            if current_time - self.magic_switch_time >= self.switch_duration_cooldown:
                self.can_switch_magic = True

        if not self.vulnerable:
            if current_time - self.hurt_time >= self.invulnerability_duration:
                self.vulnerable = True

    def animate(self):
       #print("\n\nANIMATIONS#print \n\n")
       #print(self.frame_index)
       #print(self.status)
        #print(self.animations)
        animation = self.animations.get(self.status) or []
        masks = self.masks.get(self.status) or []
        if not animation or not masks:
            if getattr(self, "_dash_runtime", None) is not None or getattr(self, "_charge_runtime", None) is not None or getattr(self, "_leap_runtime", None) is not None:
                fallback_status = "down_idle"
                animation = self.animations.get(fallback_status, [])
                masks = self.masks.get(fallback_status, [])
                if not animation or not masks:
                    return
            else:
                fallback_status = "down_idle"
                animation = self.animations.get(fallback_status, [])
                masks = self.masks.get(fallback_status, [])
                self.status = fallback_status
                self.frame_index = 0
                if not animation or not masks:
                    return
        self.frame_index += self.advance_frame()
        if self.frame_index >= len(animation):
            if self.status == "sit_down":
                self.status = "sit_idle"
                self.frame_index = 0
                animation = self.animations.get(self.status) or animation
                masks = self.masks.get(self.status) or masks
            elif self.status == "sit_up":
                self.status = self.post_seat_status
                self.seated_object = None
                self.seat_anchor_world = None
                self.seat_player_offset = (0, 0)
                self.frame_index = 0
                animation = self.animations.get(self.status) or animation
                masks = self.masks.get(self.status) or masks
            else:
                self.frame_index = 0
        self.image = animation[int(self.frame_index)]
        self.mask = masks[int(self.frame_index)]
        if self.status.startswith("sit_"):
            self._position_sprite_for_seat()
        else:
            self.plant_sprite_on_hitbox()
        if not self.vulnerable:
            alpha = self.wave_value()
            self.image.set_alpha(alpha)
        else:
            self.image.set_alpha(255)

    def get_full_weapon_damage(self):
        base_damage = self.stats["attack"]
        weapon_damage = weapon_data[self.weapon]["damage"]
        return base_damage + weapon_damage

    def get_full_magic_damage(self):
        base_damage = self.stats["magic"]
        spell_damage = magic_data[self.magic]["strength"]
        return base_damage + spell_damage

    def get_value_by_index(self, index):
        key = self.upgrade_stat_order[index]
        return self.stats.get(key, self.max_stats.get(key, 0))

    def player_death(self):
        if self.health <= 0:
            self.health = 0
            self.is_dead = True

    def get_cost_by_index(self, index):
        key = self.upgrade_stat_order[index]
        return self.upgrade_cost[key]

    def energy_recovery(self):
        if self.is_dead or self.health <= 0:
            return
        if self.energy < self.stats["energy"]:
            self.energy += 0.05 * self.stats["magic"]
        else:
            self.energy = self.stats["energy"]


    def health_recovery(self):
        if self.is_dead or self.health <= 0:
            return
        if self.health < self.stats["health"]:
            self.health += 0.05 * self.stats["vitality"]
        else:
            self.health = self.stats["health"]


    def update(self, QuadTree,entity_quad_tree, dt=None,layout_switch= False):#
        if self.is_dead:
            return

        self.input()
        self.cooldowns()
        self.get_status()
        self.animate()
        self.action_controller.tick(self, dt, QuadTree, entity_quad_tree)
        if not self.action_controller.suppresses_locomotion(self):
            self.move(self.stats["speed"], QuadTree, entity_quad_tree)
        self.energy_recovery()
        self.health_recovery()
        self.player_death()

    def _resolve_post_seat_status(self):
        if "left" in self.status:
            return "left_idle"
        if "right" in self.status:
            return "right_idle"
        if "up" in self.status:
            return "up_idle"
        return "down_idle"

    def _seat_world_target(self):
        if self.seat_anchor_world is None:
            return None
        ax, ay = self.seat_anchor_world
        ox, oy = self.seat_player_offset
        return (ax + ox, ay + oy)

    def _position_sprite_for_seat(self):
        target = self._seat_world_target()
        if target is None:
            self.plant_sprite_on_hitbox()
            return
        self.rect = position_surface_mask_midbottom_at(self.image, self.mask, target)
        # Seat world point is the authority here (not hitbox). Locomotion uses
        # the opposite split: hitbox owns position, rect is planted from it.
        if hasattr(self, "hitbox"):
            self.hitbox.center = self.rect.center

    def _import_sit_animation_override(self, sit_paths):
        if not isinstance(sit_paths, dict):
            return
        changed = False
        for key in ("sit_down", "sit_idle", "sit_up"):
            raw_path = sit_paths.get(key)
            if not raw_path or not os.path.isdir(raw_path):
                continue
            try:
                frames = import_folder(raw_path)
            except Exception:
                frames = []
            if not frames:
                continue
            if hasattr(self, "TILESIZE"):
                frames = [
                    pygame.transform.scale(frame, (self.TILESIZE, self.TILESIZE))
                    for frame in frames
                ]
            self.animations[key] = frames
            self.masks[key] = frames_to_masks(frames)
            changed = True
        if changed:
            self.frame_index = 0

    def begin_seated_interaction(self, seat_obj, anchor_world, player_offset=(0, 0), sit_paths=None):
        self.attacking = False
        self.direction.x = 0
        self.direction.y = 0
        self.post_seat_status = self._resolve_post_seat_status()
        if sit_paths:
            self._import_sit_animation_override(sit_paths)
        self.seated_object = seat_obj
        self.seat_anchor_world = (int(anchor_world[0]), int(anchor_world[1]))
        self.seat_player_offset = (int(player_offset[0]), int(player_offset[1]))
        self.status = "sit_down"
        self.frame_index = 0

    def begin_stand_from_seat(self):
        if self.status == "sit_up":
            return
        self.attacking = False
        self.direction.x = 0
        self.direction.y = 0
        self.status = "sit_up"
        self.frame_index = 0
        

class SpecificPlayer(BasePlayer):
    def __init__(self,
                 selected_player_info_dir,
                 pos,
                 groups,
                 obstacle_sprites, 
                 create_attack,
                 destroy_attack,
                 create_magic,
                 create_trap,
                 initial_stats,
                 level,
                 input_manager,
                 QuadTree,
                 entity_quad_tree,
                 layout_callback_update_quad_tree = None):
        
        character_assets = selected_player_info_dir
        super().__init__(pos,
                         groups,
                         obstacle_sprites,
                         create_attack,
                         destroy_attack,
                         create_magic,
                         create_trap,
                         initial_stats,
                         level,
                         input_manager,
                         character_assets,
                         QuadTree,
                         entity_quad_tree,
                         layout_callback_update_quad_tree )
        

        # Set the initial image for the specific player
        self.image = pygame.image.load(character_assets + "down_idle/0.png").convert_alpha()
#        print(character_assets + "/down_idle/0.png")
        self.rect = self.image.get_rect(topleft=pos)
         # Initialize hitbox for SpecificPlayer
        self.hitbox = self.rect.inflate(-6, HITBOX_OFFSET["player"])
        self.capture_feet_anchor()
# You can add more specific player classes here in a similar fashion.
