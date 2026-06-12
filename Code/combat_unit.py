import pygame
import math
from Settings import *
from Entity import Entity
from Support import *
import os
from hashRect import HashableRect
from CombatStrategy import MeleeCombatStrategy,RangedCombatStrategy,MixedCombatStrategy
import random
import os
import cv2
from Interaction import InteractionContext
    
# This is for file importing but is in Main.py anyways
os.chdir(os.path.dirname(os.path.abspath(__file__)))

class CombatUnit(Entity):
    _AGGRO_CACHE_TTL = 60

    def __init__(self,
                 monster_name,
                 pos,
                 groups,
                 obstacle_sprites,
                 combat_context,
                 #damage_player,
                 #redirect_projectile_callback,
                 #trigger_death_particles,
                 #add_exp,
                 persistent,
                 layout_callback_update_quad_tree = None,
                 animations_left_right_indicator=True,
                 #fire_projectile=None,  # Callback to level to fire projectile
                 special_attacks=None,
                 item_drop_info=None,
                 combat_config=None,
                 team_id="enemy",
                 sprite_type=None):
        
        
        #                  monster_name=config['type'], 
        #                 pos=scaled_pos,
        #                 groups=[self.level.layout_manager.visible_sprites, self.level.attackable_sprites],
        #                 obstacle_sprites=self.level.layout_manager.obstacle_sprites,
        #                 context=combat_context,
        #                 special_attacks=special_attacks,
        #                 persistent=
        
        #print("combat_context")
        #print(combat_context)
        if "update_quad_tree" in combat_context.keys():
            layout_callback_update_quad_tree = combat_context["update_quad_tree"]
        else:
            layout_callback_update_quad_tree = None
        
        # General Setup
        super().__init__(groups=groups,
                         layout_callback_update_quad_tree = layout_callback_update_quad_tree)
        self.groups = groups
        self.team_id = team_id
        self.sprite_type = sprite_type if sprite_type is not None else "enemy"
        self.recent_attacker_team_id = None
        self.recent_attacker_until_ms = 0
        # --- aggro target cache ---
        # None = never scanned; False = cached empty; else real target sprite
        self._aggro_target_cache = None
        self._aggro_cache_frame = -1
        self._aggro_cache_prefer_team = None

        #if monster_name == 'ice_mage':
            #print("icemagesoecial")
            #print(special_attacks)
        ##### where are these special attacks and combat config coming from ? 
        #     I thought it was all monster info, its not being used currently, right ? 
        
        
        # 1. understand where special attacks and combat config are coming from now
        
        # 2. define simply combat_config as the part of monsterinfo used for combat
        
        # 3. adapt combat strategy to define its own config and use correct values.
        
        
        self.special_attacks = special_attacks or {} # NOT USED RIGHT NOW
        self.combat_config = combat_config or {}    # ALSO NEVER PASSED, IS FROM MONSTER INFO NOT USED RIGHT NOW
        self.combat_context = combat_context or {}
        
        
        #if monster_name == 'ice_mage':
            #print("icemagesoecial2")
            #print(self.special_attacks)
        
        
        if item_drop_info:
            self.item_drop_info = item_drop_info
        self.animations_left_right_indicator = animations_left_right_indicator
        
        # Graphics Setup
        if animations_left_right_indicator:
            self.import_graphics_left_right(monster_name)
        else:
            self.import_graphics(monster_name)

        if monster_name == "tribey_snake":
            random_scale = random.gauss(1.5, 0.2)
            self.scale_animations(random_scale)

        self.status = "idle"
        self.direction_string = "right"
        if self.animations_left_right_indicator:
            self.image = self.animations[self.status][self.direction_string][self.frame_index]
        else:
            self.image = self.animations[self.status][self.frame_index]

        # Movement
        self.rect = self.image.get_rect(topleft=pos)
        self.hitbox = self.rect.inflate(0, -10)
        self.obstacle_sprites = obstacle_sprites
        self.direction_update_time = 500
        self.last_direction_update_time = pygame.time.get_ticks()

        # Stats
        self.monster_name = monster_name
        monster_info = monster_data[self.monster_name]
        self.health = monster_info["health"]
        self.exp = monster_info["exp"]
        self.speed = monster_info["speed"]
        self.resistance = monster_info["resistance"]
        
        #### All in combat config now
        self.combat_config = monster_info["combat_config"]
        # self.attack_damage = monster_info["damage"]
        # self.attack_radius = monster_info["attack_radius"]
        # self.notice_radius = monster_info["notice_radius"]
        # self.melee_attack_radius = monster_info.get("melee_attack_radius", self.attack_radius)
        self.attack_type = monster_info["attack_type"]
        

        # TODO: still a bunch of stuff not in the combat config...look at these variables below.
        #         just used for cooldowns which is done badly anyway should have each attack on cooldown
        #         must define classes for attacks i think
        
        #         parrys are also passed separately to the combat strategy for some reason 
        
                # attack type used to define combat strategy sub class.
        
        # END TODO
        
        self.melee_attacks = self.combat_config.get("melee_attacks", [])
        self.ranged_attacks = self.combat_config.get("ranged_attacks", [])
        self.melee_parry_chance = self.combat_config.get("melee_parry_chance", 0)
        self.projectile_parry_chance = self.combat_config.get("projectile_parry_chance", 0)
        self.parry_cooldown = self.combat_config.get("parry_cooldown", 1000)


        #### 

        self.masks = get_or_build_entity_masks(
            self.monster_name,
            self.animations,
            self.animations_left_right_indicator,
            skip_disk=(self.monster_name == "tribey_snake"),
        )
        self.mask = None

        # Player Interaction
        self.can_attack = True
        self.attack_time = pygame.time.get_ticks()
        
        
        ### Is this series of cooldowns used ? urg cool down done super wierd
        
        # TODO: cooldowns just takes the max cooldown from all attacks, i can do better than this
        
        self.attack_cooldown = max([attack["cooldown"] for attack in self.melee_attacks + self.ranged_attacks], default=400)
        #self.damage_player = damage_player
        #self.trigger_death_particles = trigger_death_particles
        #self.add_exp = add_exp
        self.persistent = persistent

        # Attacks
        #self.fire_projectile = fire_projectile
        self.last_attack_action_time = 0
        self.attack_action_cooldown = self.attack_cooldown
        self.last_parry_time = 0

        # Freeze logic 
        self.frozen = False  
        self.freeze_time = 0

        # Invincibility Timer
        self.vulnerable = True
        self.hit_time = None
        self.invincibility_duration = 300

        # Sounds
        self.death_sound = pygame.mixer.Sound("../Audio/Death.wav")
        self.hit_sound = pygame.mixer.Sound("../Audio/Hit.wav")
        self.attack_sound = pygame.mixer.Sound(monster_info["attack_sound"])
        self.death_sound.set_volume(0.6)
        self.hit_sound.set_volume(0.6)
        self.attack_sound.set_volume(0.3)
        
        # Combat Strategy Setup
        parry_effects = {
            "melee_parry_chance": self.melee_parry_chance,
            "projectile_parry_chance": self.projectile_parry_chance,
            "parry_cooldown": self.parry_cooldown
        }
        #self.redirect_projectile_callback = redirect_projectile_callback

        if self.attack_type == "melee":
            self.combat_strategy = MeleeCombatStrategy(self.melee_attacks,
                                                       parry_effects,
                                                       movement_behavior=None,
                                                       combat_context=self.combat_context,
                                                       special_attacks=self.special_attacks
                                                       #redirect_projectile_callback = redirect_projectile_callback,
                                                       #fire_projectile = self.fire_projectile
                                                       )
        elif self.attack_type == "ranged":
            self.combat_strategy = RangedCombatStrategy(self.ranged_attacks,
                                                        parry_effects,
                                                        movement_behavior=None,
                                                        #redirect_projectile_callback = redirect_projectile_callback,
                                                        #fire_projectile = self.fire_projectile
                                                        combat_context=self.combat_context,
                                                       special_attacks=self.special_attacks
                                                        )
        elif self.attack_type == "mixed":
            self.combat_strategy = MixedCombatStrategy(self.melee_attacks,
                                                       self.ranged_attacks,
                                                       parry_effects,
                                                       movement_behavior=None,
                                                       combat_context=self.combat_context,
                                                       special_attacks=self.special_attacks
                                                       #redirect_projectile_callback = redirect_projectile_callback,
                                                       #fire_projectile = self.fire_projectile,
                                                       
                                                       )
 
        else:
            # just coz i dont have settings correctly made for al lmonsters atm.
            self.combat_strategy = MeleeCombatStrategy(self.melee_attacks,
                                                       parry_effects,
                                                       movement_behavior=None,
                                                       combat_context=self.combat_context,
                                                       special_attacks=self.special_attacks
                                                       #redirect_projectile_callback = redirect_projectile_callback,
                                                       #fire_projectile = self.fire_projectile
                                                       )

    def scale_animations(self, scale_factor):
        for status, animations in self.animations.items():
            if isinstance(animations, dict):
                for direction, frames in animations.items():
                    self.animations[status][direction] = [pygame.transform.scale(frame, (int(frame.get_width() * scale_factor), int(frame.get_height() * scale_factor))) for frame in frames]
            else:
                self.animations[status] = [pygame.transform.scale(frame, (int(frame.get_width() * scale_factor), int(frame.get_height() * scale_factor))) for frame in animations]

    
    def freeze(self, duration=3000):
        """Freeze the enemy, stopping all movement and actions."""
        self.frozen = True
        self.freeze_time = pygame.time.get_ticks()
        self.freeze_duration = duration
        self.frozen_image = self.apply_frozen_effect(self.image)  # Apply effect and save
        
    def apply_frozen_effect(self, image):
        """Applies a turquoise color overlay only to the non-transparent parts of an image."""
        frozen_image = image.copy()  # Make a copy to not alter the original
        turquoise_overlay = pygame.Surface(image.get_size(), pygame.SRCALPHA)
        
        # Fill the overlay with turquoise color
        turquoise_overlay.fill((64, 224, 208, 128))  # Semi-transparent turquoise
        
        # Create a mask using the alpha value of the original image
        alpha_mask = pygame.surfarray.pixels_alpha(image).copy()
        
        # Set this alpha mask to the turquoise overlay
        pygame.surfarray.pixels_alpha(turquoise_overlay)[:] = alpha_mask
        
        # Blit the turquoise overlay onto the frozen image using BLEND_RGBA_MULT for color multiply
        frozen_image.blit(turquoise_overlay, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
        
        return frozen_image


    def get_direction_as_string(self):
        return "right" if self.direction.x >= 0 else "left"

    
     
    
    def thaw(self):
        """Thaw the enemy, resuming normal behavior."""
        #print('THAWED')
        self.frozen = False
        #print(self.status)
        #print(self.animations[self.status])
        #print(self.direction_string  )
        #print(self.animations_left_right_indicator)
        if self.animations_left_right_indicator:            
            self.image = self.animations[self.status][self.direction_string][int(self.frame_index)]
        else:
            self.image = self.animations[self.status][int(self.frame_index)]
        self.rect = self.image.get_rect(center=self.hitbox.center)
        


    def is_dead(self):
        """Check if the enemy is dead."""
        return self.health <= 0

    
    
    def import_graphics_left_right(self, name):
        from ImageCache import ImageCache
        self.animations = {
            "idle": {"right": [], "left": []},
            "move": {"right": [], "left": []},
            "attack": {"right": [], "left": []}
        }
        main_path = f"../Graphics/Monsters/{name}/"

        # Standard animations — cache flipped frames in ImageCache so the GPU atlas picks them up.
        # All instances of the same monster share the same Surface objects for both directions.
        for animation in self.animations.keys():
            right_frames = import_folder(main_path + animation)
            self.animations[animation]["right"] = right_frames
            flipped_key = ImageCache.folder_cache_key(main_path + animation + "__flipped", None)
            if flipped_key not in ImageCache._folder_cache:
                ImageCache._folder_cache[flipped_key] = [
                    pygame.transform.flip(img, True, False) for img in right_frames
                ]
            self.animations[animation]["left"] = ImageCache._folder_cache[flipped_key]

        # Check for SpecialAttacks folder
        special_attacks_path = os.path.join(main_path, "SpecialAttacks")
        if os.path.exists(special_attacks_path) and os.path.isdir(special_attacks_path):
            for special_attack in os.listdir(special_attacks_path):
                special_attack_path = os.path.join(special_attacks_path, special_attack)
                if os.path.isdir(special_attack_path):
                    right_frames = import_folder(special_attack_path)
                    self.animations[special_attack] = {"right": right_frames, "left": []}
                    flipped_key = ImageCache.folder_cache_key(special_attack_path + "__flipped", None)
                    if flipped_key not in ImageCache._folder_cache:
                        ImageCache._folder_cache[flipped_key] = [
                            pygame.transform.flip(img, True, False) for img in right_frames
                        ]
                    self.animations[special_attack]["left"] = ImageCache._folder_cache[flipped_key]



    def import_graphics_left_right_old(self,name):
        self.animations = {
        "idle": {"right": [], "left": []}, 
        "move": {"right": [], "left": []}, 
        "attack": {"right": [], "left": []}
                        }
        main_path = f"../Graphics/Monsters/{name}/"
        for animation in self.animations.keys():
            self.animations[animation]["right"] = import_folder(main_path + animation)
            # To get left animations, flip the images horizontally
            self.animations[animation]["left"] = [pygame.transform.flip(img, True, False) for img in self.animations[animation]["right"]]

    def import_graphics(self, name):
        self.animations = {"idle": [], "move": [], "attack": []}
        main_path = f"../Graphics/Monsters/{name}/"
        for animation in self.animations.keys():
            self.animations[animation] = import_folder(main_path + animation)
        # print(f"name : {name}")
        # print(f"path : {main_path + animation}")
        # print(f"Loaded animations for {name}: {self.animations}")

    def get_target_distance_direction(self, target):
        #print("getting player distance")
        enemy_vec = pygame.math.Vector2(self.rect.center)
        target_vec = pygame.math.Vector2(target.rect.center)
        #print(player_vec)
        distance = (target_vec - enemy_vec).magnitude()
        #print(f"player : {player_vec}")
        #print(f"enemy : {enemy_vec}")
        #print(distance)
        
        if distance > 0:
            direction = (target_vec - enemy_vec).normalize()
        else:
            direction = pygame.math.Vector2()

        return(distance, direction)

    def get_player_distance_direction(self, player):
        return self.get_target_distance_direction(player)

    def _is_valid_aggro_target(self, candidate):
        if candidate is self:
            return False
        if not hasattr(candidate, "rect"):
            return False
        if hasattr(candidate, "health") and getattr(candidate, "health", 1) <= 0:
            return False
        return True

    def _notice_radius(self):
        return float(self.combat_config.get("notice_radius", math.inf))

    def _current_prefer_team(self, now):
        retaliate_until = getattr(self, "retaliate_until_ms", 0)
        retaliate_team = getattr(self, "retaliate_team_id", None)
        if retaliate_team and now < retaliate_until:
            return retaliate_team
        if now < self.recent_attacker_until_ms:
            return self.recent_attacker_team_id
        return None

    def _aggro_cache_valid(self, now, frame_number):
        if self._aggro_target_cache is None:
            return False
        if frame_number - self._aggro_cache_frame >= CombatUnit._AGGRO_CACHE_TTL:
            return False
        if self._current_prefer_team(now) != self._aggro_cache_prefer_team:
            return False
        if self._aggro_target_cache is False:
            return True
        if not self._is_valid_aggro_target(self._aggro_target_cache):
            return False
        distance, _ = self.get_target_distance_direction(self._aggro_target_cache)
        if distance > self._notice_radius():
            return False
        return True

    def _pick_best_hostile(self, resolver, candidates, prefer_team, notice_radius, restrict_prefer_team):
        best_target = None
        best_distance = math.inf
        for candidate in candidates:
            if not self._is_valid_aggro_target(candidate):
                continue
            if restrict_prefer_team and prefer_team is not None:
                if getattr(candidate, "team_id", None) != prefer_team:
                    continue
            if not resolver.can_aggro(self, candidate):
                continue
            distance, _ = self.get_target_distance_direction(candidate)
            if distance > notice_radius:
                continue
            if distance < best_distance:
                best_distance = distance
                best_target = candidate
        return best_target

    def select_hostile_target(self, frame_number=0, entity_id_map=None, entity_quad_tree=None):
        level = self.combat_context.get("level") if isinstance(self.combat_context, dict) else None
        resolver = getattr(level, "interaction_resolver", None) if level is not None else None
        if resolver is None:
            return self.combat_context.get("default_target")

        now = pygame.time.get_ticks()
        if self._aggro_cache_valid(now, frame_number):
            return None if self._aggro_target_cache is False else self._aggro_target_cache

        prefer_team = self._current_prefer_team(now)
        notice_radius = self._notice_radius()
        use_spatial = (
            entity_quad_tree is not None
            and entity_id_map is not None
            and notice_radius != math.inf
        )
        if use_spatial:
            r = int(notice_radius)
            query_rect = self.rect.inflate(r * 2, r * 2)
            hits = entity_quad_tree.hit(HashableRect(query_rect, self.id))
            candidates = [
                entity_id_map[h._id]
                for h in hits
                if h._id in entity_id_map
            ]
        else:
            visible = getattr(level.layout_manager, "visible_sprites", None) if level else None
            candidates = visible.sprites() if visible is not None else []

        best_target = self._pick_best_hostile(
            resolver, candidates, prefer_team, notice_radius, restrict_prefer_team=True
        )
        if best_target is None and prefer_team is not None:
            best_target = self._pick_best_hostile(
                resolver, candidates, prefer_team, notice_radius, restrict_prefer_team=False
            )

        self._aggro_target_cache = best_target if best_target is not None else False
        self._aggro_cache_frame = frame_number - (self.id % CombatUnit._AGGRO_CACHE_TTL)
        self._aggro_cache_prefer_team = prefer_team
        return best_target

    def get_status(self, player):
        distance = self.get_player_distance_direction(player)[0]

        if distance <= self.attack_radius and self.can_attack:
            if self.status != "attack":
                self.frame_index = 0
            self.status = "attack"
        elif distance <= self.notice_radius:
            self.status = "move"
        else:
            self.status = "idle"
    #@profile
    
    
    
    def actions(self, player, quadtree=None):
        if self.status != "Summoning":  # TODO: Only perform actions if not summoning - should be if casting, need logic here 
            self.combat_strategy.decide_action(self, player)
            self.combat_strategy.move(self, player)
            if self.status == "attack":
                self.combat_strategy.execute_attack(self, player)
            self.combat_strategy.parry(self, player, quadtree)
        else:
            self.combat_strategy.execute_attack(self, player)
        
    
    def actions_old(self, player, quadtree = None):
        
        #print(f"Combat strategy : {self.combat_strategy}")
        
        self.combat_strategy.decide_action(self, player)
        self.combat_strategy.move(self, player)
        if self.status == "attack":
            self.combat_strategy.execute_attack(self, player)
        self.combat_strategy.parry(self, player, quadtree)
    


    #@profile
    def animate(self):
        
       # print(self.status)
       # print(self.frame_index)
       # print(self.can_attack)
        
        
        
        
        if self.frozen:
            #print("FROZEN")
            self.image = self.frozen_image
            new_rect = self.image.get_rect(center=self.hitbox.center)
            #if new_rect.size != self.rect.size:
                
                #print(f"Rect size mismatch: original {self.rect.size}, new {new_rect.size}")
            self.rect = new_rect
        else:
        
            if self.animations_left_right_indicator:
                direction_string = self.get_direction_as_string()
                animation = self.animations[self.status][direction_string]  
                #print(self.sprite_type)
                #print(self.monster_name)
                #print(self.masks)
                masks = self.masks[self.status][direction_string]
            else:
                animation = self.animations[self.status]
                masks = self.masks[self.status]
            
            self.frame_index += self.animation_speed
            if self.frame_index >= len(animation):
                if self.status == "attack":
                    self.can_attack = False
                    self.status = "idle"
                    ## TODO: THIS BEING HERE AGAIN IS A MESS ITS TO FORCE CHANGE IN ANIMATION RIGHT NOW, NOT EVEN SURE IT HELPS ( WAS STUK IN ATTACK ANIMATION TOO LONG )
                    if self.animations_left_right_indicator:
                        direction_string = self.get_direction_as_string()
                        animation = self.animations[self.status][direction_string]   
                        masks = self.masks[self.status][direction_string]
                    else:
                        animation = self.animations[self.status]
                        masks = self.masks[self.status]
                    
                self.frame_index = 0
    
            self.image = animation[int(self.frame_index)]
            self.mask = masks[int(self.frame_index)]
            self.rect = self.image.get_rect(center = self.hitbox.center)
    
            if not self.vulnerable:
                alpha = self.wave_value()
                self.image.set_alpha(alpha)
            else:
                self.image.set_alpha(255)
                
                
    #@profile
    def cooldowns(self):
        current_time = pygame.time.get_ticks()
        if not self.can_attack:
            if current_time - self.attack_time >= self.attack_cooldown:
                self.can_attack = True

        if not self.vulnerable:
            if current_time - self.hit_time >= self.invincibility_duration:
                self.vulnerable = True
    #@profile
    def get_damage(self, player, attack_type):
        if self.vulnerable:
            self.hit_sound.play()
            self.direction = self.get_player_distance_direction(player)[1] # Faces you when hit ? not sure about this
            if attack_type == "weapon":
                self.health -= player.get_full_weapon_damage()
            else:
                self.health -= player.get_full_magic_damage()
            self.hit_time = pygame.time.get_ticks()
            #self.vulnerable = False

    def can_receive_interaction(self, ctx: InteractionContext):
        if ctx.kind == "effect_state":
            return True
        if ctx.kind != "damage":
            return False
        if ctx.source_team == self.team_id:
            return False
        return True

    def receive_interaction(self, ctx: InteractionContext):
        if ctx.kind == "effect_state":
            super().receive_interaction(ctx)
            return
        if ctx.kind != "damage":
            return
        source_team = ctx.source_team
        if source_team and source_team != self.team_id:
            self.recent_attacker_team_id = source_team
            retaliation_window_ms = 12000
            level = self.combat_context.get("level") if isinstance(self.combat_context, dict) else None
            resolver = getattr(level, "interaction_resolver", None) if level is not None else None
            policy = getattr(resolver, "faction_policy", None) if resolver is not None else None
            if policy is not None and hasattr(policy, "resolve_faction"):
                faction_def = policy.resolve_faction(getattr(self, "team_id", None))
                if isinstance(faction_def, dict):
                    configured_window = faction_def.get("retaliation_window_ms")
                    if isinstance(configured_window, int) and configured_window >= 0:
                        retaliation_window_ms = configured_window
            self.recent_attacker_until_ms = pygame.time.get_ticks() + retaliation_window_ms
            self._aggro_target_cache = None
        source = ctx.source
        if source is not None and hasattr(source, "get_full_weapon_damage") and hasattr(source, "get_full_magic_damage"):
            attack_type = "weapon" if ctx.attack_type == "weapon" else "magic"
            self.get_damage(source, attack_type)
            return
        amount = ctx.amount
        if amount is None:
            return
        if self.vulnerable:
            self.health -= amount
            self.hit_time = pygame.time.get_ticks()
    #@profile
    def take_environmental_damage(self, amount, damage_type):
        """Apply environmental damage (e.g. heat); uses same vulnerability and invincibility as get_damage."""
        if self.vulnerable:
            self.health -= amount
            self.hit_time = pygame.time.get_ticks()
            self.check_death()
    #@profile
    def check_death(self):
        if self.health <= 0:
            self.layout_callback_update_quad_tree( obstacle_sprite = HashableRect( self.rect, self.id ),
                                                   remove_existing= True,
                                                   alive = False )# confusing its a callback passed to all entities, this is child , it can use it right ? 
            self.kill()
            #### TODO , add frozen or not end to monster name for frozen death particles.
            self.combat_context["trigger_death_particles"](self.rect.center, self.monster_name)
            self.combat_context["add_exp"](self.exp)
            self.death_sound.play()
            
    def hit_reaction(self):
        if not self.vulnerable:
            self.direction *= -self.resistance
    #@profile
    def update(self, QuadTree , entity_quad_tree, dt = None):   
        current_time = pygame.time.get_ticks()
        if self.frozen and current_time - self.freeze_time > self.freeze_duration:
            self.thaw()
        if not self.frozen and self.status == 'move':
            self.move(speed = self.speed,
                      QuadTree = QuadTree ,
                      entity_quad_tree = entity_quad_tree)
            self.hit_reaction()
        self.animate()
        self.cooldowns()
        self.check_death()


    def resume_default(self):
        self.status = "idle"
        self.direction = pygame.math.Vector2(0, 0)

    def combat_update(self, player=None, quadtree=None, frame_number=0, entity_id_map=None):
        if not self.frozen:
            target = self.select_hostile_target(
                frame_number=frame_number,
                entity_id_map=entity_id_map,
                entity_quad_tree=quadtree,
            )
            if target is None:
                self.resume_default()
                return
            self.actions(target, quadtree)

    def enemy_update(self, player=None, quadtree=None, frame_number=0, entity_id_map=None):
        """Deprecated: use combat_update."""
        self.combat_update(
            player, quadtree, frame_number=frame_number, entity_id_map=entity_id_map
        )
