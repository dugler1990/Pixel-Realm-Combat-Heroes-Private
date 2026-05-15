import copy
import json
import math
import random
import pygame
from Enemy import Enemy  # Make sure to import your Enemy class
from Settings import TILESIZE
from game_logging import get_debug_logger
from random import randint

_spawner_log = get_debug_logger("spawner")


def _distance_point_to_rect(px: float, py: float, rx: float, ry: float, rw: float, rh: float) -> float:
    """Shortest distance from point (px, py) to axis-aligned rectangle [rx, rx+rw] x [ry, ry+rh]."""
    if rw <= 0 or rh <= 0:
        return math.hypot(px - rx, py - ry)
    cx = min(max(px, rx), rx + rw)
    cy = min(max(py, ry), ry + rh)
    return math.hypot(px - cx, py - cy)


from Eskimo import Eskimo
from IceClone import IceClone
from Trap import Trap
from PolarBear import PolarBear
from Settings import monster_data
import SpecialAttacks
from enemy_drop_defaults import get_default_item_drop_for_monster

CHARACTER_CLASSES = {
    'eskimo': Eskimo,
    'polarbear':PolarBear
    # Add other neutral character classes here as you create them.
}

class Spawner:
    def __init__(self, level, persistent_enemy_data, fire_projectile):# could do better way to access all level call backs.
        self.level = level  # Reference to the main game class to access game state, level manager, etc.
        self.enemies = []  # List to keep track of all spawned enemies
        self.timed_spawns = {}        
        self.spawn_timers = {}  # Timers for timed enemy spawns
        self.persistent_enemy_data = persistent_enemy_data
        self.spawn_areas = [] 
        self.neutral_characters = []
        self.fire_projectile = fire_projectile
        self.global_spawn_limits = self._normalize_global_spawn_limits(
            getattr(level, "global_spawn_limits", None)
        )

    def _resolve_source_team(self, owner=None, explicit_team=None, fallback_team="neutral"):
        if isinstance(explicit_team, str) and explicit_team.strip():
            return explicit_team.strip()
        owner_team = getattr(owner, "team_id", None)
        if isinstance(owner_team, str) and owner_team.strip():
            return owner_team.strip()
        return fallback_team

    def _validate_spawn_team_id(self, spawn_team_id, source_object_id=None):
        if not isinstance(spawn_team_id, str) or not spawn_team_id.strip():
            return None
        normalized = spawn_team_id.strip()
        resolver = getattr(self.level, "interaction_resolver", None)
        if resolver is None or not hasattr(resolver, "is_known_team"):
            return normalized
        if resolver.is_known_team(normalized):
            return normalized
        _spawner_log.warning(
            "Spawner object_id=%r has unknown spawn_team_id=%r; spawn blocked by policy",
            source_object_id,
            normalized,
        )
        return None

    def spawn_trap(self, trap_config):
        # Check the type of trap to spawn based on a key in the configuration, for example:
        if trap_config['class'] == IceClone:
            trap = IceClone(
                pos=trap_config['pos'],
                groups=trap_config['groups'],
                image_path=trap_config['image_path'],
                animation_player=self.level.animation_player,
                effect_type=trap_config['effect_type'],
                death_animation='ice_clone_death_1',
                add_exp=self.level.add_exp,
                target_type=trap_config.get('target_type', 'enemies'),
                trigger=trap_config.get('trigger', 'timer'),
                lifespan=trap_config.get('lifespan', 3000),
                radius=trap_config.get('radius', 5),
                health=trap_config.get('health', 100),
                exp_value=trap_config.get('exp_value', 0)
            )
            trap.owner = trap_config.get('owner')
            trap.source_team = self._resolve_source_team(
                owner=trap.owner,
                explicit_team=trap_config.get('source_team'),
                fallback_team="neutral",
            )
            trap.source_kind = trap_config.get('source_kind', 'special')
            trap.attack_type = trap_config.get('attack_type', trap_config.get('effect_type', 'special'))
            trap.amount = trap_config.get('amount')
            trap.tags = set(trap_config.get('tags', {'special'}))
            #print(trap_config)
        else:
            # Default to the general Trap class if no specific class is required
            trap = Trap(
                pos=trap_config['pos'],
                groups=trap_config['groups'],
                image_path=trap_config['image_path'],
                animation_player=self.level.animation_player,
                effect_type=trap_config['effect_type'],
                add_exp=self.level.add_exp,  # This needs to be provided from your level or game environment
                target_type=trap_config.get('target_type', 'all'),
                trigger=trap_config.get('trigger', 'timer'),
                lifespan=trap_config.get('lifespan', 5000),
                radius=trap_config.get('radius', 100),
                health=trap_config.get('health', 100),
                exp_value=trap_config.get('exp_value', 50)
            )
            trap.owner = trap_config.get('owner')
            trap.source_team = self._resolve_source_team(
                owner=trap.owner,
                explicit_team=trap_config.get('source_team'),
                fallback_team="neutral",
            )
            trap.source_kind = trap_config.get('source_kind', 'trap')
            trap.attack_type = trap_config.get('attack_type', trap_config.get('effect_type', 'trap'))
            trap.amount = trap_config.get('amount')
            trap.tags = set(trap_config.get('tags', {'trap'}))
    
        # Adding the trap to sprite groups is handled in the Trap's __init__, so we just return the trap
        return trap

    
    def set_layout_callback_update_quad_tree(self, func):
        self.layout_callback_update_quad_tree = func

    def choose_enemy_based_on_weights(self, weights):
        total_weight = sum(weights.values())
        random_value = randint(1, total_weight)
        for enemy, weight in weights.items():
            if random_value <= weight:
                return enemy
            random_value -= weight


    def load_enemy_info(self, path):
        with open(path, 'r') as file:
            self.enemy_configs = json.load(file)

    def add_spawn_area(self, spawn_matrix, spawner_config, obj_info):
        self.spawn_areas.append({
            'matrix': spawn_matrix,
            'config': spawner_config,
            'object_info': obj_info,  # Store object info if needed for position reference
            'spawn_timer':0,
            'spawn_scale_timer':0,
            'debug_state': None,
        })
        _spawner_log.debug(
            "Added spawn area object_id=%r anchor=(%.2f, %.2f) matrix=%dx%d enemy_keys=%s neutral_keys=%s "
            "frequency=%s spawn_limits=%s spawn_number=%s distance=%s spawn_team_id=%r",
            obj_info.get("object_id"),
            float(obj_info.get("anchor_tx", 0.0)),
            float(obj_info.get("anchor_ty", 0.0)),
            len(spawn_matrix[0]) if spawn_matrix and len(spawn_matrix) > 0 else 0,
            len(spawn_matrix),
            sorted((spawner_config.get("enemy_spawn_weights") or {}).keys()),
            sorted((spawner_config.get("neutral_spawn_weights") or {}).keys()),
            spawner_config.get("frequency"),
            spawner_config.get("spawn_limits"),
            spawner_config.get("spawn_number"),
            spawner_config.get("distance", 2000),
            spawner_config.get("spawn_team_id"),
        )

    def _set_area_debug_state(self, area, state, message, *args):
        if area.get("debug_state") == state:
            return
        area["debug_state"] = state
        _spawner_log.debug(message, *args)

    def _normalize_global_spawn_limits(self, raw_limits):
        result = {
            "general": None,
            "enemy": None,
            "neutral": None,
            "types": {},
        }
        if not isinstance(raw_limits, dict):
            return result
        for key in ("general", "enemy", "neutral"):
            value = raw_limits.get(key)
            if isinstance(value, int) and value >= 0:
                result[key] = value
        raw_types = raw_limits.get("types")
        if isinstance(raw_types, dict):
            for actor_type, cap in raw_types.items():
                if isinstance(cap, int) and cap >= 0:
                    result["types"][str(actor_type)] = cap
        return result

    def _is_sprite_alive(self, sprite):
        alive_method = getattr(sprite, "alive", None)
        if callable(alive_method):
            return bool(alive_method())
        return True

    def _live_enemies(self):
        return [enemy for enemy in self.enemies if self._is_sprite_alive(enemy)]

    def _live_neutrals(self):
        return [neutral for neutral in self.neutral_characters if self._is_sprite_alive(neutral)]

    def _all_live_actors(self):
        enemies = self._live_enemies()
        neutrals = self._live_neutrals()
        return enemies + neutrals, enemies, neutrals

    def _actor_spawn_type(self, actor, fallback_name=""):
        value = getattr(actor, "_spawn_type", None)
        if isinstance(value, str) and value:
            return value
        value = getattr(actor, "monster_name", None)
        if isinstance(value, str) and value:
            return value
        return fallback_name

    def _count_actors(self, actors, actor_type=None, source_object_id=None):
        total = 0
        for actor in actors:
            if source_object_id is not None and getattr(actor, "_spawn_source_object_id", None) != source_object_id:
                continue
            if actor_type is not None:
                if self._actor_spawn_type(actor) != actor_type:
                    continue
            total += 1
        return total

    def _build_limit_snapshot(self, spawn_kind, spawn_type, source_object_id):
        live_all, live_enemies, live_neutrals = self._all_live_actors()
        kind_actors = live_enemies if spawn_kind == "enemy" else live_neutrals
        return {
            "global_general": len(live_all),
            "global_enemy": len(live_enemies),
            "global_neutral": len(live_neutrals),
            "global_type": self._count_actors(live_all, actor_type=spawn_type),
            "spawner_general": self._count_actors(live_all, source_object_id=source_object_id),
            "spawner_kind": self._count_actors(kind_actors, source_object_id=source_object_id),
            "spawner_type": self._count_actors(
                kind_actors,
                actor_type=spawn_type,
                source_object_id=source_object_id,
            ),
        }

    def _evaluate_spawn_limits(self, config, spawn_kind, spawn_type, source_object_id):
        per_spawner_limits = config.get("spawn_limits") if isinstance(config.get("spawn_limits"), dict) else {}
        global_limits = self.global_spawn_limits
        snapshot = self._build_limit_snapshot(spawn_kind, spawn_type, source_object_id)

        _spawner_log.debug(
            "Spawner object_id=%r evaluating limits kind=%s type=%s snapshot=%s per_spawner=%s global=%s",
            source_object_id,
            spawn_kind,
            spawn_type,
            snapshot,
            per_spawner_limits,
            global_limits,
        )

        checks = [
            ("per_spawner", "general", snapshot["spawner_general"], per_spawner_limits.get("general")),
            ("per_spawner", spawn_kind, snapshot["spawner_kind"], per_spawner_limits.get(spawn_kind)),
            ("per_spawner", f"type:{spawn_type}", snapshot["spawner_type"], (per_spawner_limits.get("types") or {}).get(spawn_type)),
            ("global", "general", snapshot["global_general"], global_limits.get("general")),
            ("global", spawn_kind, snapshot[f"global_{spawn_kind}"], global_limits.get(spawn_kind)),
            ("global", f"type:{spawn_type}", snapshot["global_type"], (global_limits.get("types") or {}).get(spawn_type)),
        ]

        for scope, key, current, cap in checks:
            if cap is None:
                continue
            if current >= cap:
                return False, {
                    "scope": scope,
                    "key": key,
                    "current": current,
                    "cap": cap,
                }
        return True, {
            "scope": "none",
            "key": "none",
            "current": None,
            "cap": None,
        }

    def handle_spawn_areas(self, player, dt):
        #current_time = pygame.time.get_ticks() # 
        #print("spawn areas:")
        #print(self.spawn_areas)
        for area in self.spawn_areas:
            
            area["spawn_scale_timer"] += dt
            area["spawn_timer"] += dt
            #print("config")
            #print(area["config"])
            if "time_scaled" in area["config"] :
                #print("timescaled bool")
                #print(area["config"]['time_scaled'])
                if area["config"]['time_scaled']:
                    if area["spawn_scale_timer"] > 10:
                        
                        # reset
                        area["spawn_scale_timer"] = 0 
                        
                        # update number of spawned items by config
                        if area["config"]["scale_type"] == "multiple":
                            area['config']["spawn_number"] = min( area['config']["spawn_number"] * 2, area["config"]["scale_max"] )
                            #print("spawn number")
                            #print(area['config']["spawn_number"])
            
            # print("SPAWN ATTEMPT")
            # print(f"area pos : {area['object_info']['x_pos']}")
            # print(f"area pos : {area['object_info']['y_pos']}")
            
            config = area['config']
            # Player proximity: distance to spawner AABB in game pixels (not only top-left — large rects need this)
            proximity = config.get("distance", 2000)
            if isinstance(proximity, (int, float)):
                oi = area["object_info"]
                px = float(player.rect.center[0])
                py = float(player.rect.center[1])
                if oi.get("rect_w_px") is not None and float(oi.get("rect_w_px", 0)) > 0:
                    distance = _distance_point_to_rect(
                        px,
                        py,
                        float(oi["rect_x_px"]),
                        float(oi["rect_y_px"]),
                        float(oi["rect_w_px"]),
                        float(oi["rect_h_px"]),
                    )
                else:
                    ax = oi.get("anchor_tx", oi.get("x_pos", 0.0))
                    ay = oi.get("anchor_ty", oi.get("y_pos", 0.0))
                    distance = math.hypot(
                        float(ax) * TILESIZE - px,
                        float(ay) * TILESIZE - py,
                    )
                if distance > float(proximity):
                    self._set_area_debug_state(
                        area,
                        "waiting_distance",
                        "Spawner object_id=%r waiting for proximity distance=%.1f threshold=%.1f player_px=(%.1f, %.1f)",
                        oi.get("object_id"),
                        distance,
                        float(proximity),
                        px,
                        py,
                    )
                    continue
                self._set_area_debug_state(
                    area,
                    "in_range",
                    "Spawner object_id=%r entered proximity distance=%.1f threshold=%.1f",
                    oi.get("object_id"),
                    distance,
                    float(proximity),
                )
                    
            #print(config['next_spawn_time'])
            #print(current_time)
            #print("printing spawn timer")
            #print(area["spawn_timer"])
            #print('frequency')
            #print(config['frequency'])
            
            if 'frequency' not in config or area["spawn_timer"]>= config['frequency']:
                area["spawn_timer"]= 0
                self._set_area_debug_state(
                    area,
                    "ready_to_spawn",
                    "Spawner object_id=%r ready to spawn frequency=%s spawn_limits=%s spawn_number=%s enemies_live=%d neutrals_live=%d",
                    area["object_info"].get("object_id"),
                    config.get("frequency"),
                    config.get("spawn_limits"),
                    config.get("spawn_number"),
                    len(self._live_enemies()),
                    len(self._live_neutrals()),
                )
                
                #print("len enemies :")
                #print(len(self.enemies))
                
                #print("enemies")
                #print(self.enemies)
                
                
                #print( f" number enemier : {len(self.enemies)}, spawn limit : { config['spawn_limit']} " )
                number_new_sprites = max(0, int(config.get("spawn_number", 1)))
                source_object_id = area["object_info"].get("object_id")
                for _ in range(number_new_sprites):
                    spawn_pos = self.choose_random_spawn_pos(area['matrix'], area['object_info'])
                    if not spawn_pos:
                        _spawner_log.debug(
                            "Spawner object_id=%r has no valid spawn position in matrix",
                            source_object_id,
                        )
                        continue

                    enemy_weights = config.get('enemy_spawn_weights') or {}
                    neutral_weights = config.get('neutral_spawn_weights') or {}
                    enemy_total = sum(enemy_weights.values()) if enemy_weights else 0
                    neutral_total = sum(neutral_weights.values()) if neutral_weights else 0
                    if enemy_total <= 0 and neutral_total <= 0:
                        _spawner_log.debug(
                            "Spawner object_id=%r has no usable weight pools at spawn time",
                            source_object_id,
                        )
                        continue

                    spawn_kind = 'enemy'
                    if enemy_total > 0 and neutral_total > 0:
                        total = enemy_total + neutral_total
                        roll = random.uniform(0, total)
                        spawn_kind = 'enemy' if roll < enemy_total else 'neutral'
                    elif neutral_total > 0:
                        spawn_kind = 'neutral'

                    if spawn_kind == 'neutral':
                        spawn_type = self.choose_enemy_based_on_weights(neutral_weights)
                    else:
                        spawn_type = self.choose_enemy_based_on_weights(enemy_weights)

                    allowed, reason = self._evaluate_spawn_limits(
                        config=config,
                        spawn_kind=spawn_kind,
                        spawn_type=spawn_type,
                        source_object_id=source_object_id,
                    )
                    if not allowed:
                        _spawner_log.debug(
                            "Spawner object_id=%r blocked kind=%s type=%s scope=%s key=%s current=%s cap=%s",
                            source_object_id,
                            spawn_kind,
                            spawn_type,
                            reason["scope"],
                            reason["key"],
                            reason["current"],
                            reason["cap"],
                        )
                        continue

                    _spawner_log.debug(
                        "Spawner object_id=%r allowed spawn kind=%s type=%s pos=(%.2f, %.2f)",
                        source_object_id,
                        spawn_kind,
                        spawn_type,
                        float(spawn_pos[0]),
                        float(spawn_pos[1]),
                    )

                    if spawn_kind == 'neutral':
                        neutral_attributes = config.get('neutral_attributes') or {}
                        attrs = neutral_attributes.get(spawn_type, {})
                        validated_team = self._validate_spawn_team_id(
                            config.get('spawn_team_id'),
                            source_object_id=source_object_id,
                        )
                        if config.get('spawn_team_id') and validated_team is None:
                            continue
                        spawn_cfg = {
                            'type': spawn_type,
                            'pos': spawn_pos,
                            'attributes': attrs if isinstance(attrs, dict) else {},
                            '_spawn_source_object_id': source_object_id,
                            'spawn_team_id': validated_team,
                        }
                        self.spawn_neutral(spawn_cfg)
                        continue

                    # Should get this info from standard dict in spawner i think easier than in each spawner config
                    if spawn_type == 'demon_dog':
                        special_attacks = {'projectile':'demon_dog_projectile'}
                        fire_projectile = self.fire_projectile
                    else:
                        special_attacks = monster_data[spawn_type].get('special_attacks',None)
                        fire_projectile = self.fire_projectile

                    spawn_cfg = {
                        'type': spawn_type,
                        'pos': spawn_pos,
                        'fire_projectile': fire_projectile,
                        'special_attacks': special_attacks,
                        '_spawn_source_object_id': source_object_id,
                        'spawn_team_id': self._validate_spawn_team_id(
                            config.get('spawn_team_id'),
                            source_object_id=source_object_id,
                        ),
                    }
                    if config.get('spawn_team_id') and spawn_cfg['spawn_team_id'] is None:
                        continue
                    if 'item_drop_info' in config:
                        spawn_cfg['item_drop_info'] = config['item_drop_info']
                    self.spawn_enemy(spawn_cfg)
            else:
                self._set_area_debug_state(
                    area,
                    "waiting_timer",
                    "Spawner object_id=%r waiting for timer current=%.3f frequency=%s",
                    area["object_info"].get("object_id"),
                    float(area["spawn_timer"]),
                    config.get("frequency"),
                )
                    
                
                #config['next_spawn_time'] = current_time + config['frequency'] from previous implementation


    def choose_random_spawn_pos(self, spawn_matrix, object_info):
        """
        Spawn positions are float game-tile coords (same scale as layout_manager anchors).
        Each matrix cell is one TMX tile wide/tall = one game tile in world space.
        """
        ax = float(object_info.get("anchor_tx", object_info.get("x_pos", 0.0)))
        ay = float(object_info.get("anchor_ty", object_info.get("y_pos", 0.0)))
        possible_positions = []
        for row_i, row in enumerate(spawn_matrix):
            for col_i, cell in enumerate(row):
                if cell == 1:
                    spawn_tx = ax + col_i + random.random()
                    spawn_ty = ay + row_i + random.random()
                    possible_positions.append((spawn_tx, spawn_ty))
        return random.choice(possible_positions) if possible_positions else None



    def generate_combat_context(self, level, combat_config):
        context = {
            "level": level,
            "default_target": level.player,
        }
        if 'damage_player' in combat_config.keys():# keys is not the best, its got True False atm for no reason , no biggy TODO:
            context['damage_player'] = level.damage_player
        if 'damage_player' in combat_config.keys():
            context['enemy_melee_hit'] = level.emit_enemy_melee_hit
        if 'fire_projectile' in combat_config.keys():
            context['fire_projectile'] = level.fire_projectile
        if 'redirect_projectile' in combat_config.keys():
            context['redirect_projectile'] = level.redirect_projectile_callback
        if 'trigger_death_particles' in combat_config.keys():
            context['trigger_death_particles'] = level.trigger_death_particles
        if 'add_exp' in combat_config.keys():
            context['add_exp'] = level.add_exp
        if 'spawn_enemy' in combat_config.keys():
            context['spawn_enemy'] = level.spawner.spawn_enemy
        if 'update_quad_tree' in combat_config.keys():
            context['update_quad_tree'] = level.layout_manager.add_obstacle_sprite_to_quad_tree
        if 'spawn_enemy' in combat_config.keys():
            context['spawn_enemy'] = self.spawn_enemy
                
        # Add other methods as needed based on combat_config
        return context


    def spawn_enemy(self, config, pos=None):

        #print( f"enemy spawn attempt {config}, {pos}" )
        if not pos:  # If no position is provided, use the one from the config
            pos = config['pos']
        # Scale position by TILESIZE
        scaled_pos = (pos[0] * TILESIZE, pos[1] * TILESIZE)
        
        monster_config = monster_data[config['type']]
        #if config['type'] == 'ice_mage':
            #print("monster_config in spawner for icemage")
            #print(monster_config)
        
        combat_config = monster_config.get('combat_config', {})
        #if config['type'] == 'ice_mage':
            #print("combat_config in spawner for icemage")
            #print(combat_config)
        combat_context = combat_config.get('combat_context', {})
        
        #if config['type'] == 'ice_mage':
            #print("combat_context in spawner for icemage")
            #print(combat_context)
        
        combat_context = self.generate_combat_context(self.level, combat_context)
        
        #if config['type'] == 'ice_mage':
            #print("final combat_config in spawner for icemage")
            #print(combat_context)
        
        # Create special attacks based on the configuration
        special_attacks_config = combat_config.get('special_attacks', [])
        special_attacks = [SpecialAttacks.create_special_attack(attack) for attack in special_attacks_config]

        #if config['type'] == 'ice_mage':
           # print("special attacks config")
            #print(special_attacks_config)
            #print(special_attacks)

        
## TODO: the level is passed to the spawner.... should this use callbacks ? hmm
        if 'item_drop_info' in config:
            item_drop_info = copy.deepcopy(config['item_drop_info'])
            default_drop = get_default_item_drop_for_monster(config['type'])
            if (
                default_drop
                and 'gold_drop' in default_drop
                and 'gold_drop' not in item_drop_info
            ):
                item_drop_info['gold_drop'] = default_drop['gold_drop']
        else:
            item_drop_info = get_default_item_drop_for_monster(config['type'])
        enemy = Enemy(  monster_name=config['type'], 
                        pos=scaled_pos,
                        groups=[self.level.layout_manager.visible_sprites, self.level.attackable_sprites],
                        obstacle_sprites=self.level.layout_manager.obstacle_sprites,
                        combat_context=combat_context,
                        special_attacks=special_attacks,
                        persistent=config.get('persistent', False),
                        item_drop_info=item_drop_info )
        spawn_team_id = config.get("spawn_team_id")
        if isinstance(spawn_team_id, str) and spawn_team_id.strip():
            enemy.team_id = spawn_team_id.strip()
        enemy._spawn_source_object_id = config.get('_spawn_source_object_id')
        enemy._spawn_type = str(config.get('type', ''))
        self.enemies.append(enemy)
        _spawner_log.debug(
            "Spawned enemy type=%s tile_pos=(%.2f, %.2f) pixel_pos=(%.1f, %.1f) persistent=%s source_object_id=%r team_id=%r",
            config['type'],
            float(pos[0]),
            float(pos[1]),
            float(scaled_pos[0]),
            float(scaled_pos[1]),
            config.get('persistent', False),
            config.get('_spawn_source_object_id'),
            getattr(enemy, "team_id", None),
        )
        

 

    def spawn_neutral(self, config, pos=None):
        #print(f"neutral spawn attempt {config}, {pos}")
        if not pos:  # If no position is provided, use the one from the config
            pos = config['pos']
        # Scale position by TILESIZE
        scaled_pos = (pos[0] * TILESIZE, pos[1] * TILESIZE)

        char_type = config['type']
        #print(char_type)
        char_class = CHARACTER_CLASSES.get(char_type)
        attributes = config.get('attributes', {})
        if not isinstance(attributes, dict):
            attributes = {}

        if char_class:
            try:
                # Instantiate the neutral character with the necessary sprite groups and callbacks
                neutral_character = char_class(
                    pos=scaled_pos,
                    groups=[self.level.layout_manager.visible_sprites, self.level.attackable_sprites],
                    obstacle_sprites=self.level.layout_manager.obstacle_sprites,
                    get_tile_valid_actions_callback=self.level.get_tile_valid_actions,  # Confusing bcoz this is the only place this is used and written in level
                    update_item_spawner_callback=self.level.item_spawner.update_spawn_positions,  # You need to define this callback in your level class
                    update_tile_image_callback=self.level.layout_manager.update_tile_image, 
                    trigger_death_particles = self.level.trigger_death_particles,# You need to define this callback in your level class
                    layout_callback_update_quad_tree = self.layout_callback_update_quad_tree,
                    **attributes
                 )
                spawn_team_id = config.get("spawn_team_id")
                if isinstance(spawn_team_id, str) and spawn_team_id.strip():
                    neutral_character.team_id = spawn_team_id.strip()
                neutral_character._spawn_source_object_id = config.get('_spawn_source_object_id')
                neutral_character._spawn_type = str(char_type)
                self.neutral_characters.append(neutral_character)
                _spawner_log.debug(
                    "Spawned neutral type=%s tile_pos=(%.2f, %.2f) pixel_pos=(%.1f, %.1f) attrs_keys=%s source_object_id=%r team_id=%r",
                    char_type,
                    float(pos[0]),
                    float(pos[1]),
                    float(scaled_pos[0]),
                    float(scaled_pos[1]),
                    sorted(attributes.keys()),
                    config.get('_spawn_source_object_id'),
                    getattr(neutral_character, "team_id", None),
                )
            except TypeError as e:
                _spawner_log.debug("Failed to spawn neutral %s: %s", char_type, e)
        else:
            _spawner_log.debug("Unknown neutral character type: %s", char_type)


    def update(self, current_layout):
        self.handle_timed_spawns()
        self.spawn_random_enemies(current_layout)
        self.manage_persistent_enemies(current_layout)

    def handle_timed_spawns(self):
        current_time = pygame.time.get_ticks()
        for config in self.enemy_configs:
            if config.get('spawn_mode') == 'timed' and current_time > self.spawn_timers.get(config['type'], 0):
                self.spawn_enemy(config)
                self.spawn_timers[config['type']] = current_time + config['spawn_interval']

    def spawn_random_enemies(self, current_layout):
        for config in self.enemy_configs:
            if config.get('spawn_mode') == 'random' and config.get('layout') == current_layout:
                if random.random() < config.get('spawn_chance', 0.01):  # Adjust spawn chance as needed
                    self.spawn_enemy(config)

   
    
    def restore_persistent_enemies(self, layout_path):
        if layout_path in self.persistent_enemy_data:
            for enemy_state in self.persistent_enemy_data[layout_path]:
                # Reinitialize the enemy based on the saved state
                enemy = Enemy(
                    enemy_state['type'],
                    enemy_state['position'],
                    [self.level.layout_manager.visible_sprites, self.level.attackable_sprites],
                    self.level.layout_manager.obstacle_sprites,
                    self.level.damage_player,
                    self.level.trigger_death_particles,
                    self.level.add_exp,
                    persistent=True
                )
                enemy.health = enemy_state['health']  # Restore the health state
                self.enemies.append(enemy)


    def track_enemy_layouts(self):
        for enemy in self.enemies:
            if enemy.can_follow:
                # Update the enemy's last known layout and position
                enemy.last_known_layout = self.level.current_layout
                enemy.last_known_pos = (enemy.rect.x, enemy.rect.y)


    
    def on_layout_change(self, layout_path):
        # Load the current layout's enemy configurations
        enemy_config_path = os.path.join(layout_path, "enemies.json")
        with open(enemy_config_path, 'r') as file:
            current_layout_enemies = json.load(file)

        # Iterate through current layout enemies and check against tracked persistent enemies
        for enemy_config in current_layout_enemies:
            enemy_key = self.generate_enemy_key(enemy_config)  # A unique identifier for each enemy type and position

            if enemy_key in self.persistent_enemies:
                # Restore the enemy state if it's marked as persistent and not killed
                persisted_enemy = self.persistent_enemies[enemy_key]
                if not persisted_enemy['killed']:
                    self.restore_enemy(persisted_enemy)
                continue

            # Spawn new enemies if not persistent or previously killed
            self.spawn_enemy(enemy_config)

    def on_layout_update(self):
        current_time = pygame.time.get_ticks()

       # Handle timed enemy spawns
        for enemy_key, spawn_data in self.timed_spawns.items():
            if current_time >= spawn_data['next_spawn_time']:
                self.spawn_enemy(spawn_data['config'])
                spawn_data['next_spawn_time'] += spawn_data['interval']

        # Handle conditional spawns (example: based on player position)
        # This could include checking player's position and spawning enemies accordingly
