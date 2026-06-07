### Plan here is to make a Level class that uses Layout classes to 
#   re-render the level when a <trigger> (door) is stepped on.
from Eskimo import Eskimo
import json
from Spawner import Spawner
from ItemSpawner import ItemSpawner
from Item import Item
from Inventory import draw_belt_hud
from ItemVisual import ItemVisual
import pygame
from Settings import *
from game_logging import get_debug_logger

_game_flow_log = get_debug_logger("game_flow")
_combat_log = get_debug_logger("combat")
from Tile import Tile
from Trigger import Trigger
from Player import SpecificPlayer
from Debug import debug
from Support import *
from random import choice, randint
from Weapon import Weapon
from UI import UI
from Particles import AnimationPlayer
from Magic import MagicPlayer
from Evasion import EvasionPlayer
from Upgrade import Upgrade
import copy
import os
import sys
import random
import time
from loot_table import resolve_gold_drop, resolve_loot_table
from AnimationSprite import AnimationSprite
from Trap import Trap
from Tree import Tree 
from Torch import Torch
from Weather import Weather
from AnimatedEnvironmentSprite import AnimatedEnvironmentSprite
from WaterTile import WaterTile
from WeatherOverlay import WeatherOverlay
from DaytimeBrightnessOverlay import DaytimeBrightnessOverlay
import math
from GrassManager import GrassManager
from QuadTree import QuadTree
from QuadTree import QuadTreeManager
from QuadTreeItem import QuadTreeItem
from pygame.math import Vector2
from pygame.mask import from_surface  

from hashRect import HashableRect
from Entity import Entity
from tmx_layout_manager import LayoutManager
from benchmark_runtime import BENCHMARK_RUNTIME
from rts_validation_runtime import RTS_VALIDATION_RUNTIME
from Interaction import InteractionContext, InteractionResolver
from rts import RtsSession, RtsWorldSim
from rts.world_adapter import RtsWorldAdapter
from Support import resolve_env_interactable_path
#with open('triggers.json',r) as file
#triggers = json.loads(file.read())


#tmxdata = load_pygame("../levels/tmx//map.tmx")
#### Imports to move  : 



class BrightnessCircle:
    def __init__(self, center, radius, brightness):
        self.center = center
        self.radius = radius
        self.brightness = brightness
    
    def intersects(self, other_circle):
        """Check if two circles overlap by comparing distances between centers and their radii."""
        distance = Vector2(self.center).distance_to(other_circle.center)
        return distance < (self.radius + other_circle.radius)

    def get_surface(self, size):
        """Create a surface for this circle's brightness."""
        surface = pygame.Surface(size, pygame.SRCALPHA)
        brightness_color = (255 * self.brightness, 255 * self.brightness, 255 * self.brightness, 255)
        pygame.draw.circle(surface, brightness_color, self.center, self.radius)
        return surface


def draw_circle_with_max_brightness(surface, circle, max_brightness_mask, mask_pos):
    """Draws the circle on the surface with max brightness in overlapping areas."""
    brightness_color = (255 * circle.brightness, 255 * circle.brightness, 255 * circle.brightness, 255)
    pygame.draw.circle(max_brightness_mask, brightness_color, mask_pos, circle.radius)
    surface.blit(max_brightness_mask, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)


class LevelRtsWorldAdapter(RtsWorldAdapter):
    """Narrow RTS host adapter for the current action-RPG level."""

    def __init__(self, level):
        self.level = level

    def get_player(self):
        return self.level.player

    def get_display_surface(self):
        return self.level.display_surface

    def get_visible_sprites(self):
        return self.level.layout_manager.visible_sprites

    def get_map_bounds(self):
        visible = self.level.layout_manager.visible_sprites
        ground = getattr(visible, "ground_surface", None)
        if ground is not None and hasattr(visible, "min_x") and hasattr(visible, "min_y"):
            return pygame.Rect(visible.min_x, visible.min_y, ground.get_width(), ground.get_height())
        sprites = getattr(visible, "sprites", lambda: [])()
        rects = [sprite.rect for sprite in sprites if hasattr(sprite, "rect")]
        if not rects:
            return None
        bounds = rects[0].copy()
        for rect in rects[1:]:
            bounds.union_ip(rect)
        return bounds

    def request_player_stand(self):
        self.level._stand_from_seat()

    def is_player_dead(self):
        return bool(getattr(self.level.player, "is_dead", False))

    def get_obstacle_sprites(self):
        return getattr(self.level.layout_manager, "obstacle_sprites", None)

    def get_obstacle_quad_tree(self):
        return getattr(self.level.layout_manager, "obstacle_quad_tree", None)

    def get_walk_grid_cache(self):
        return getattr(self.level.layout_manager, "walk_grid_cache", None)

    def get_rts_registry(self):
        return getattr(self.level.layout_manager, "rts_registry", None)

    def get_layout_callback_update_quad_tree(self):
        return self.level.layout_manager.add_obstacle_sprite_to_quad_tree

    def get_selectable_sprites(self, throne_profile_id=""):
        lm = self.level.layout_manager
        registry = getattr(lm, "rts_registry", None)
        selectables = list(getattr(lm, "environment_interactables", None) or [])
        for sprite in lm.visible_sprites.sprites():
            if getattr(sprite, "rts_selectable", False) and sprite not in selectables:
                selectables.append(sprite)
        if throne_profile_id and registry is not None:
            chief = registry.get_chief_for_throne(throne_profile_id)
            filtered = []
            for sprite in selectables:
                kind = str(getattr(sprite, "kind", "")).strip().lower()
                if kind == "chief":
                    if sprite is chief:
                        filtered.append(sprite)
                    continue
                if kind == "resource_node":
                    fid = getattr(self.level.rts_session, "faction", None)
                    if fid is not None and getattr(sprite, "faction_id", "") == fid.id:
                        filtered.append(sprite)
                    elif fid is None:
                        filtered.append(sprite)
                    continue
                if kind == "build_site":
                    fid = getattr(self.level.rts_session, "faction", None)
                    if fid is not None and getattr(sprite, "faction_id", "") == fid.id:
                        filtered.append(sprite)
                    elif fid is None:
                        filtered.append(sprite)
                    continue
                filtered.append(sprite)
            return filtered
        return selectables

    def get_sprite_groups(self):
        lm = self.level.layout_manager
        return [lm.obstacle_sprites, lm.visible_sprites]

    def get_rts_population_count(self, faction_id=""):
        from rts.assets import normalize_faction_id

        fid = normalize_faction_id(faction_id)
        registry = self.get_rts_registry()
        if registry and fid:
            return len(registry.workers_by_faction.get(fid, []))
        return super().get_rts_population_count()


def subtract_circle(circle1, circle2, surface):
    """Subtract circle2's overlapping region from circle1's brightness."""
    mask1 = pygame.mask.from_surface(circle1.get_surface(surface.get_size()))
    mask2 = pygame.mask.from_surface(circle2.get_surface(surface.get_size()))
    
    # Get the intersecting area
    intersection_mask = mask1.overlap_mask(mask2, (0, 0))
    
    # Subtract the intersection from circle1
    inverse_intersection = pygame.mask.Mask(mask1.get_size())
    inverse_intersection.invert()
    clipped_mask = mask1.overlap_mask(inverse_intersection, (0, 0))

    return clipped_mask

def mask_to_surface(mask, color, size):
    """Convert a mask to a surface with the given color and size."""
    mask_surface = pygame.Surface(size, pygame.SRCALPHA)
    mask_surface.fill((0, 0, 0, 0))  # Fill with transparent
    
    # Get the mask's pixels and draw them on the surface with the desired color
    for x in range(size[0]):
        for y in range(size[1]):
            if mask.get_at((x, y)):
                mask_surface.set_at((x, y), color)
    
    return mask_surface

#####


### Layouts will be instanciated with a path to its triggers fill

       
DEV_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.dev_reload_state.json')

LAYOUT_TO_LEVEL = {
    '../levels/tmx': 6,
    '../levels/Map7': 7,
    '../levels/Map8': 8,
}


class Level4:
    def __init__(self, input_manager, selected_player_info_dir, layouts_dir, player_stats, level_number=None, game_settings=None):
        self.level_number = level_number
        self.game_settings = game_settings
        self.benchmark_runtime = BENCHMARK_RUNTIME
        self._benchmark_summary_written = False
        self._benchmark_player_anchor = None
        self._benchmark_walls = []
        self._benchmark_wall_items = []
        self._benchmark_walls_spawned = False
        self._benchmark_wall_next_id = -1
        self.start_map(input_manager=input_manager,
                       selected_player_info_dir=selected_player_info_dir,
                       layouts_dir=layouts_dir,
                       player_stats=player_stats)


    def start_map(self,
                  input_manager,
                  selected_player_info_dir,
                  layouts_dir,
                  player_stats=None,
                  display_surface = None,
                  layout_manager= None,
                  Player = None,
                  restart = False,
                  player_position = None):
        
        self.player_base_stats = player_stats
        ## callback methods these do not actually need to be in init i think, just seems lgocial.
        self.persistent_enemy_data = {}
        standard_items_path = '../Graphics/Standard_Items/standard_items.json'
        self.item_spawner = ItemSpawner()
        self.item_spawner.load_item_mapping(standard_items_path)
        self.particle_dict = {}
        
        self.last_trigger_time = None
        self.trigger_cooldown = 5000  # 1 second cooldown
        
        if display_surface:
            # Set old display surface : maybe this is the problem actually, maybe killing the sprites kills the surface or something
            #print("set display surface from previous level")
            self.display_surface = display_surface
        else:
            self.display_surface = pygame.display.get_surface()  # This returns None Maybe i need to do what ever else is done before this
                                                                 # like what ever is in Main.py.... this is so backwards.        
            # Set up a new display surface with transparency
            self.display_surface = pygame.display.set_mode(self.display_surface.get_size(), pygame.SRCALPHA)

        
        self.weather_overlay = WeatherOverlay(self.display_surface)
        self.game_paused = False
        self._gold_popup_until_ms = 0
        self._gold_popup_amount = 0
        self.player_dead = False
        self.upgrade_menu_open = False
        self.inventory_open = False
        self._show_interact_prompt = False
        self.attack_selection_open = False 
        self.player_config_open = False
        self._frame_number = 0
        self.selected_player_info_dir = selected_player_info_dir
        self.layouts_dir = layouts_dir
        self.input_manager = input_manager
        self.input_manager.reset()
        self.current_layout = None
        self.layouts_dir = layouts_dir
        self.ui=UI()
        with open(f"{layouts_dir}/initial_layout_name.txt", "r") as file:
            initial_layout_dir = file.read().strip()
        _game_flow_log.debug("layout dir  : %s", layouts_dir)
        try:
            with open(f"{layouts_dir}/layout_general_config.txt", "r") as file:
                layout_general_config = file.read().strip()   # for now just indicates daylight, need to develop this .json format and files
        except:
            layout_general_config = "True"
        #print(f"resulting layout general config : {layout_general_config}")
        #print(type(layout_general_config))
        layout_general_config = layout_general_config.strip()
        self.daytime_layout  = layout_general_config != "False" # indicates whether we use the daytime overlay, really this should be a part of the general brightness overlay ? 
        #print(f"resulting daytime layount in level start map method : {self.daytime_layout}")
        self.wind_timer = 0
        self.wind_interval = 2000
        
        #print( initial_layout_dir )
        self.attack_sprites = pygame.sprite.Group()
        self.attackable_sprites = pygame.sprite.Group()
        self.enemy_attack_sprites = pygame.sprite.Group()
        sink = (
            self.benchmark_runtime.metrics
            if self.benchmark_runtime.enabled and self.benchmark_runtime.metrics_enabled
            else None
        )
        self.interaction_resolver = InteractionResolver(telemetry_sink=sink)


        if layout_manager :
            #print("layout was passed to the restart")
            self.layout_manager = layout_manager
            
        else:
            # Initialize LayoutManager with callbacks
            self.layout_manager = LayoutManager(
                selected_player_info_dir, 
                #tmxdata,
                TILESIZE, 
                restore_persistent_enemies_callback=self.restore_persistent_enemies,
                initialize_map_items_callback=self.initialize_map_items,  # Pass the method reference directly
                benchmark_runtime=self.benchmark_runtime,
                
                )        

        # Level-wide caps for Spawner (read in Spawner.__init__ via getattr(level, "global_spawn_limits")).
        self.global_spawn_limits = {
            "general": 130,
            "enemy": 120,
            "neutral": 10,
        }

# After player initialization in Level4
        self.spawner = Spawner( self, self.persistent_enemy_data,self.fire_projectile )
        self.layout_manager.set_spawner( self.spawner, self.layout_manager.add_obstacle_sprite_to_quad_tree )
        self.layout_manager.set_item_spawner(self.item_spawner)
        
        
        #print("JUST SET DISPLAY SCREEN ")
        #print(self.display_surface)
        #if display_surface:
            #print(display_surface)
        #else:print("None")
        
        if not restart :         
            self.layout_manager.daytime_brightness_overlay.set_display_surface(self.display_surface)
            self.layout_manager.initialize_layout( initial_layout_dir ) # Convention: initial layout is defined by naming convention       
        
        self.current_layout = initial_layout_dir

      
        #self.add_item_to_level_callback = add_item_to_level # random af not sure what this was used for .
        
        
        if not Player:
            # Instantiate the player here
            self.player = SpecificPlayer(
                self.selected_player_info_dir,
                (15 * TILESIZE, 25 * TILESIZE),
                [self.layout_manager.visible_sprites],  # Pass the visible_sprites from LayoutManager
                self.layout_manager,  # Pass the obstacle_sprites from LayoutManager
                self.create_attack,
                self.destroy_attack,
                self.create_magic,
                self.create_evasion,
                self.player_base_stats,
                self,
                self.input_manager,
                self.layout_manager.obstacle_quad_tree,
                self.layout_manager.entity_quad_tree,
                layout_callback_update_quad_tree = self.layout_manager.add_obstacle_sprite_to_quad_tree  ## TODO : rename this, its for entities, obstacles are done in the init only.
            )
           
            # Pass the player to the LayoutManager for interaction handling
            self.layout_manager.set_player(self.player)
        
        
        self.layout_manager.set_player(self.player)
        self.attackable_sprites.add(self.player)
        self._seed_default_belt_if_needed()
        self.weather = Weather()
        if self.game_settings:
            self.weather.time_speed_multiplier = self.game_settings.environment_speed
        
        
        self.upgrade = Upgrade(self.player, self.input_manager)
        self.animation_player = AnimationPlayer()
        self.magic_player = MagicPlayer(self.animation_player)
        self.evasion_player = EvasionPlayer(self.animation_player, self.create_trap)
        self.current_attack = None
        self.rts_world_adapter = LevelRtsWorldAdapter(self)
        self.rts_world_sim = RtsWorldSim()
        self.rts_world_sim.bind_navigation(self.rts_world_adapter)
        self.rts_session = RtsSession(
            self.rts_world_adapter, self.input_manager, self.rts_world_sim
        )

        self._rts_validation_driver = None
        if RTS_VALIDATION_RUNTIME.enabled:
            from rts_validation_driver import RtsValidationDriver

            self._rts_validation_driver = RtsValidationDriver()
            self._apply_benchmark_player_survivability()
        elif self.benchmark_runtime.enabled:
            self._initialize_benchmark_mode()

        if restart:
            #print(f"Player position being set to {player_position} in start_map")
            self.player.rect.topleft = player_position
            self.player.hitbox.topleft = player_position
            #print(self.player.rect.center)
            self.player.update(layout_switch = False,
                               QuadTree=self.layout_manager.obstacle_quad_tree,
                               entity_quad_tree= self.layout_manager.entity_quad_tree)
            
            # # why am i updating here twice  ? 
            # for sprite in self.layout_manager.visible_sprites:
            #     if hasattr(sprite, 'type'):
            #         if sprite.type == 'player':
            #             sprite.update()
            #print("pre")
            #self.layout_manager.obstacle_quad_tree.print_all()
            #print(f"Player position as in start map func : {player_position}")
            
            
            
            
            ###### One solution is to just get the value of whether the destination place should have daytime layout again and set it true/false.
            
            
            
            #print(f'JUST BEFORE LAST INITIALIZE LAYOUT DAYTIME VALUE : {self.daytime_layout}')
            
            
            self.layout_manager.initialize_layout( self.layouts_dir,
                                                  player_position=player_position,# Im doing something shitty here.# just need to remove, the position is actually set in this method. 
                                                  restart = True,
                                                  Player = self.player, ## unecesary, we can set player from level with the set player method.
                                                  daytime_layout = self.daytime_layout,
                                                  prepared_daytimeoverlay = None #self.layout_manager.daytime_brightness_overlay # so silly i set it above
                                                  )
            
            if self.layout_manager.daytime_brightness_overlay:
                self.layout_manager.daytime_brightness_overlay.set_display_surface(self.display_surface) # TODO: done separately in both restart and not restart....terrible

    def _initialize_benchmark_mode(self):
        random.seed(self.benchmark_runtime.seed)
        self._apply_benchmark_player_survivability()
        self._benchmark_summary_written = False
        # Initialize benchmark arena boundaries once per level.
        if not self._benchmark_walls_spawned:
            self._spawn_benchmark_boundaries()
            self._benchmark_walls_spawned = True
        if self.benchmark_runtime.matrix_enabled:
            self.benchmark_runtime.begin_matrix()
            self._start_next_benchmark_case()
        else:
            self._spawn_benchmark_entities()
            self._reset_benchmark_grass_state()
            self.layout_manager.switch_entity_broadphase_backend(
                self.benchmark_runtime.broadphase_backend,
                grid_cell_size=self.benchmark_runtime.grid_cell_size,
            )
            self.benchmark_runtime.begin_warmup()
            print(
                f"[BENCH] Warmup started label={self.benchmark_runtime.run_label} "
                f"count={self.benchmark_runtime.entity_count} "
                f"backend={self.benchmark_runtime.broadphase_backend} "
                f"grid_cell_size={self.benchmark_runtime.grid_cell_size} "
                f"swarm_neighbors={self.benchmark_runtime.simple_swarm_neighbor_limit} "
                f"floor={self.benchmark_runtime.pushback_floor_enabled} "
                f"cap={self.benchmark_runtime.pushback_cap_enabled} "
                f"max_cap={self.benchmark_runtime.pushback_max_cap} "
                f"enemy={self.benchmark_runtime.enemy_display_label()} "
                f"warmup_s={self.benchmark_runtime.warmup_seconds}",
                flush=True,
            )
            _game_flow_log.debug(
                "Benchmark mode ON: count=%s seed=%s backend=%s floor=%s cap=%s max_cap=%s enemy=%s",
                self.benchmark_runtime.entity_count,
                self.benchmark_runtime.seed,
                self.benchmark_runtime.broadphase_backend,
                self.benchmark_runtime.pushback_floor_enabled,
                self.benchmark_runtime.pushback_cap_enabled,
                self.benchmark_runtime.pushback_max_cap,
                self.benchmark_runtime.enemy_type,
            )

    def _clear_benchmark_enemies(self):
        for enemy in list(self.spawner.enemies):
            enemy.kill()
        self.spawner.enemies.clear()

    def _reset_benchmark_grass_state(self):
        visible_sprites = getattr(self.layout_manager, "visible_sprites", None)
        if visible_sprites is not None and hasattr(visible_sprites, "last_player_grass_force_center"):
            visible_sprites.last_player_grass_force_center = None

    def _draw_benchmark_overlay(self):
        if not self.benchmark_runtime.enabled:
            return

        font = pygame.font.Font(None, 24)
        padding = 8
        line_gap = 4
        snap = self.benchmark_runtime.metrics.snapshot()
        current, total = self.benchmark_runtime.matrix_progress()
        phase = self.benchmark_runtime.case_phase.upper()
        if self.benchmark_runtime.case_phase == "measure":
            elapsed = max(0.0, time.time() - self.benchmark_runtime.run_started_at)
            phase_target = self.benchmark_runtime.auto_run_seconds
        elif self.benchmark_runtime.case_phase == "warmup":
            elapsed = max(0.0, time.time() - self.benchmark_runtime.warmup_started_at)
            phase_target = self.benchmark_runtime.warmup_seconds
        else:
            elapsed = 0.0
            phase_target = 0.0

        lines = [
            f"case {current}/{total}  {phase}",
            f"enemy {self.benchmark_runtime.enemy_display_label()}  count {self.benchmark_runtime.entity_count}",
            (
                f"{self.benchmark_runtime.collision_mode}  "
                f"n={self.benchmark_runtime.simple_swarm_neighbor_limit}  "
                f"{self.benchmark_runtime.broadphase_backend}  "
                f"cell={self.benchmark_runtime.grid_cell_size}"
            ),
            (
                f"floor={'on' if self.benchmark_runtime.pushback_floor_enabled else 'off'}  "
                f"cap={'on' if self.benchmark_runtime.pushback_cap_enabled else 'off'}  "
                f"max={self.benchmark_runtime.pushback_max_cap:g}"
            ),
            f"timer {elapsed:.1f}/{phase_target:.1f}s",
            f"fps {snap['avg_fps']:.2f}  p95 {snap['p95_frame_ms']:.2f}ms",
            f"queries {int(snap['broadphase_queries'])}  cand {int(snap['candidate_collisions'])}",
        ]

        surfaces = [font.render(line, True, (255, 255, 255)) for line in lines]
        max_width = max(surface.get_width() for surface in surfaces)
        total_height = sum(surface.get_height() for surface in surfaces) + line_gap * (len(surfaces) - 1)
        panel_width = max_width + padding * 2
        panel_height = total_height + padding * 2
        panel = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 170))

        y = padding
        for surface in surfaces:
            panel.blit(surface, (padding, y))
            y += surface.get_height() + line_gap

        x = self.display_surface.get_width() - panel_width - 12
        y = self.display_surface.get_height() - panel_height - 12
        self.display_surface.blit(panel, (x, y))

    def _draw_rts_validation_overlay(self):
        if not RTS_VALIDATION_RUNTIME.enabled or not RTS_VALIDATION_RUNTIME.overlay_enabled:
            return
        state = RTS_VALIDATION_RUNTIME.overlay_state
        lines = state.get("lines") if state else None
        if not lines:
            return

        font = pygame.font.Font(None, 24)
        padding = 8
        line_gap = 4
        phase = str(state.get("phase", "RUNNING")).upper()
        phase_color = (80, 255, 120) if phase == "PASS" else (255, 80, 80) if phase == "FAIL" else (255, 255, 255)

        surfaces = []
        for i, line in enumerate(lines):
            color = phase_color if i == 0 and line == "RTS VALIDATION" else (255, 255, 255)
            surfaces.append(font.render(line, True, color))
        max_width = max(surface.get_width() for surface in surfaces)
        total_height = sum(surface.get_height() for surface in surfaces) + line_gap * (len(surfaces) - 1)
        panel_width = max_width + padding * 2
        panel_height = total_height + padding * 2
        panel = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 190))

        y = padding
        for surface in surfaces:
            panel.blit(surface, (padding, y))
            y += surface.get_height() + line_gap

        self.display_surface.blit(panel, (12, 12))

    def _start_next_benchmark_case(self):
        case = self.benchmark_runtime.start_next_matrix_case()
        if case is None:
            print("[BENCH] Matrix complete. Exiting.", flush=True)
            pygame.event.post(pygame.event.Event(pygame.QUIT))
            return False
        self._clear_benchmark_enemies()
        self._reset_benchmark_grass_state()
        self.layout_manager.switch_entity_broadphase_backend(
            case["backend"],
            grid_cell_size=case.get("grid_cell_size"),
        )
        self._spawn_benchmark_entities()
        self.benchmark_runtime.begin_warmup()
        current, total = self.benchmark_runtime.matrix_progress()
        print(
            f"[BENCH] Case {current}/{total} warmup label={self.benchmark_runtime.run_label} "
            f"count={self.benchmark_runtime.entity_count} backend={self.benchmark_runtime.broadphase_backend} "
            f"grid_cell_size={self.benchmark_runtime.grid_cell_size} "
            f"swarm_neighbors={self.benchmark_runtime.simple_swarm_neighbor_limit} "
            f"floor={self.benchmark_runtime.pushback_floor_enabled} cap={self.benchmark_runtime.pushback_cap_enabled} "
            f"max_cap={self.benchmark_runtime.pushback_max_cap} enemy={self.benchmark_runtime.enemy_display_label()} "
            f"warmup_s={self.benchmark_runtime.warmup_seconds}",
            flush=True,
        )
        return True

    def _apply_benchmark_player_survivability(self):
        health_mult = max(1.0, float(BENCHMARK_PLAYER_HEALTH_MULTIPLIER))
        boosted_max = int(max(self.player.stats.get("health", 1), 1) * health_mult)
        # Benchmark-only guard: keep player effectively unkillable during stress tests.
        boosted_max = max(boosted_max, 1_000_000)
        self.player.stats["health"] = boosted_max
        self.player.health = boosted_max

    def _benchmark_arena_tile_bounds(self):
        """Return (min_tx, max_tx, min_ty, max_ty, radius_tiles) for wall perimeter; must stay in sync with wall spawn."""
        center_tile_x = int(self.player.rect.centerx / TILESIZE)
        center_tile_y = int(self.player.rect.centery / TILESIZE)
        radius_tiles = 4
        min_tx = max(1, center_tile_x - radius_tiles)
        max_tx = min(38, center_tile_x + radius_tiles)
        min_ty = max(1, center_tile_y - radius_tiles)
        max_ty = min(38, center_tile_y + radius_tiles)
        return min_tx, max_tx, min_ty, max_ty, radius_tiles

    def _populate_benchmark_arena_grass(self):
        """Fill interior of benchmark wall rectangle with grass (grass-benchmark runs only)."""
        if not self.benchmark_runtime.grass_benchmark_enabled:
            return
        min_tx, max_tx, min_ty, max_ty, _ = self._benchmark_arena_tile_bounds()
        gm = self.layout_manager.grass_manager
        placed = 0
        # Interior: strictly inside the wall ring (walls sit on min/max edges).
        for tx in range(min_tx + 1, max_tx):
            for ty in range(min_ty + 1, max_ty):
                gm.place_tile((tx, ty), BENCHMARK_ARENA_GRASS_DENSITY, BENCHMARK_ARENA_GRASS_OPTIONS)
                placed += 1
        # Runs after random.seed in _initialize_benchmark_mode and before entity spawn; consumes RNG for blade layout.
        print(f"[BENCH] Arena grass tiles placed={placed}", flush=True)

    def _spawn_benchmark_boundaries(self):
        """Spawn tile-based benchmark boundary walls around the anchored player."""
        min_tx, max_tx, min_ty, max_ty, radius_tiles = self._benchmark_arena_tile_bounds()

        # Clear previous references in case benchmark mode is reinitialized.
        self._benchmark_walls.clear()
        self._benchmark_wall_items.clear()

        def spawn_wall_tile(tx, ty):
            # Visible debug wall surface so benchmark containment is obvious on screen.
            surface = pygame.Surface((TILESIZE, TILESIZE), pygame.SRCALPHA)
            surface.fill((255, 0, 255, 140))
            wall = Tile(
                (int(tx * TILESIZE), int(ty * TILESIZE)),
                [self.layout_manager.visible_sprites, self.layout_manager.obstacle_sprites],
                "invisible",
                surface=surface,
            )
            self._benchmark_walls.append(wall)
            wall_item = HashableRect(
                wall.rect,
                _id=self._benchmark_wall_next_id,
                mask=wall.mask,
            )
            self._benchmark_wall_next_id -= 1
            self._benchmark_wall_items.append(wall_item)
            # Register in obstacle quadtree used by entity obstacle collision.
            self.layout_manager.obstacle_quad_tree.insert(
                wall_item,
                alive=True,
                remove_existing=True,
            )
        perimeter_tiles = []
        # Top and bottom rows.
        for tx in range(min_tx, max_tx + 1):
            perimeter_tiles.append((tx, min_ty))
            perimeter_tiles.append((tx, max_ty))
        # Left and right columns, excluding corners already added.
        for ty in range(min_ty + 1, max_ty):
            perimeter_tiles.append((min_tx, ty))
            perimeter_tiles.append((max_tx, ty))
        for tx, ty in perimeter_tiles:
            spawn_wall_tile(tx, ty)
        print(
            f"[BENCH] Spawned arena walls radius_tiles={radius_tiles} tiles={len(perimeter_tiles)}",
            flush=True,
        )
        self._populate_benchmark_arena_grass()

    def _restore_player_for_benchmark_spawn(self):
        """Reset player to the layout spawn position before each benchmark spawn ring."""
        if self._benchmark_player_anchor is None:
            self._benchmark_player_anchor = self.player.hitbox.center
        cx, cy = self._benchmark_player_anchor
        self.player.hitbox.center = (cx, cy)
        self.player.rect.center = self.player.hitbox.center
        self.player.velocity.update(0, 0)
        self.player.direction.update(0, 0)

    def _spawn_benchmark_entities(self):
        self._restore_player_for_benchmark_spawn()
        target_count = max(0, int(self.benchmark_runtime.entity_count))
        self.spawner.enemies.clear()
        center_tile_x = int(self.player.rect.centerx / TILESIZE)
        center_tile_y = int(self.player.rect.centery / TILESIZE)
        max_ring = max(1, int(BENCHMARK_SPAWN_MAX_RING))
        positions = []
        for ring in range(1, max_ring + 1):
            for dy in range(-ring, ring + 1):
                for dx in range(-ring, ring + 1):
                    if dx == 0 and dy == 0:
                        continue
                    if max(abs(dx), abs(dy)) != ring:
                        continue
                    tx = max(1, min(38, center_tile_x + dx))
                    ty = max(1, min(38, center_tile_y + dy))
                    positions.append((tx, ty))
                    if len(positions) >= target_count:
                        break
                if len(positions) >= target_count:
                    break
            if len(positions) >= target_count:
                break

        if not self.benchmark_runtime.deterministic_spawn:
            random.shuffle(positions)

        if not positions:
            positions = [(center_tile_x, center_tile_y)]

        if len(positions) < target_count:
            print(
                f"[BENCH] Spawn ring capped at {max_ring}; repeating {len(positions)} nearby slots to reach {target_count} entities.",
                flush=True,
            )
            repeats = (target_count + len(positions) - 1) // len(positions)
            positions = (positions * repeats)[:target_count]

        mix_types = self.benchmark_runtime.expanded_enemy_type_list(target_count)
        for i, pos in enumerate(positions[:target_count]):
            et = mix_types[i] if mix_types else self.benchmark_runtime.enemy_type
            self.spawner.spawn_enemy({"type": et, "pos": pos})

    def _toggle_benchmark_backend(self):
        if self.benchmark_runtime.broadphase_backend == "quadtree":
            next_backend = "grid"
        else:
            next_backend = "quadtree"
        self.layout_manager.switch_entity_broadphase_backend(next_backend)
        self.benchmark_runtime.broadphase_backend = next_backend
        _game_flow_log.debug("Benchmark backend toggled to %s", next_backend)

    def _toggle_pushback_floor(self):
        self.benchmark_runtime.pushback_floor_enabled = not self.benchmark_runtime.pushback_floor_enabled
        _game_flow_log.debug("Benchmark pushback floor enabled=%s", self.benchmark_runtime.pushback_floor_enabled)

    def _toggle_pushback_cap(self):
        self.benchmark_runtime.pushback_cap_enabled = not self.benchmark_runtime.pushback_cap_enabled
        _game_flow_log.debug("Benchmark pushback cap enabled=%s", self.benchmark_runtime.pushback_cap_enabled)
        
           # print("post")
            #self.layout_manager.obstacle_quad_tree.print_all()

    #def initialize_map_items(self, layout_path):
    #    initial_items_path = os.path.join(layout_path, 'initial_map_items.json')
    #    items_info = self.item_spawner.spawn_fixed_items(initial_items_path)
    #    self.layout_manager.place_items_on_map(items_info)
    def check_trap_triggers(self, trap):
        # Use circle-based collision detection to determine if enemies are within the trap's radius
        enemies_in_range = pygame.sprite.spritecollide(trap, self.layout_manager.spawner.enemies, False, pygame.sprite.collide_circle)
        return enemies_in_range
    # def check_trap_triggers(self,trap):
    #      enemies_in_range =  [enemy for enemy in self.layout_manager.spawner.enemies if trap.rect.colliderect(enemy.rect.inflate(trap.radius, trap.radius))]
    #      return enemies_in_range
    def create_trap(self, trap_config):
        """Method to create a trap using the spawner."""
        return self.layout_manager.spawner.spawn_trap(trap_config)
    ##@profile
    def get_tile_valid_actions(self, position, only_tile_below = True):
        """
        Determines the type of tile at the given position.
        
        :param position: A tuple (x, y) representing the position to check.
        :return: A string representing the tile type, or None if not found.
        """
        #print(f"tile below :{only_tile_below}")
        #print(f"position: {position}")
        if not only_tile_below:
            tiles = {}
            tiles.update( {'on':self.layout_manager.tile_map.get(position)} )
            position = (position[0] + TILESIZE, position[1])
            tiles.update( {'right':self.layout_manager.tile_map.get(position)} )
            position = (position[0] - 2*TILESIZE, position[1])
            tiles.update( {'left':self.layout_manager.tile_map.get(position)} )
            position = (position[0], position[1] + TILESIZE)
            tiles.update( {'below':self.layout_manager.tile_map.get(position)} )
            position = (position[0], position[1] - 2*TILESIZE)
            tiles.update( {'above':self.layout_manager.tile_map.get(position)} )
            
            #print(f"TILES: {tiles}")
        else:
            tiles = {'on':self.layout_manager.tile_map.get(position)}
        #print(f"identified tile : {tile} at position :{position}") # valid_I_T:{tile.valid_interaction_types}")
        #print(self.layout_manager.tile_map)
        possible_interaction_types = tiles
        possible_interaction_types_set = set()
        for place in tiles.keys():
            
            if tiles[place]:
                interaction_types = tiles[place].valid_interaction_types
                possible_interaction_types[place] = interaction_types
                
                for interaction_type in interaction_types:
                    possible_interaction_types_set.add(interaction_type)
            
        if len(possible_interaction_types_set) > 0:
            #print(possible_interaction_types)
            #print(possible_interaction_types_set)
            return [possible_interaction_types,possible_interaction_types_set]  # Assuming each Tile has a 'tile_type' attribute
        return None


    def initialize_map_items(self, item_config_path):
        """Initialize map items from configuration."""
        self.item_spawner.load_item_config(item_config_path)
        items = self.item_spawner.spawn_fixed_items()
        #print(dir(items[0]))
        for item in items:
            item.pos[0] = item.pos[0]*TILESIZE # size defined in grid squares.
            item.pos[1] = item.pos[1]*TILESIZE

            # Change required to scale position here.
            item_instance = Item(
                item.image_path,
                item.pos,
                item.item_id,
                item.effect,
                item.effect_type,
                item_type=getattr(item, "item_type", ""),
                float_offset=item.float_offset,
                float_speed=item.float_speed,
                float_direction=item.float_direction,
                float_amplitude=item.float_amplitude,
                belt_allowed=getattr(item, "belt_allowed", False),
            )
            self.layout_manager.add_item_visual(item_instance)

    def _update_loot_container_proximity(self):
        from InteractableChest import InteractableChest

        self._show_interact_prompt = False
        env = getattr(self.layout_manager, "environment_interactables", None) or []
        if getattr(self, "game_paused", False) or getattr(self, "inventory_open", False):
            for sprite in env:
                if isinstance(sprite, InteractableChest) and not getattr(
                    sprite, "opened", False
                ):
                    sprite.notify_proximity(False)
            return
        for sprite in env:
            if not isinstance(sprite, InteractableChest):
                continue
            if getattr(sprite, "opened", False):
                continue
            margin = getattr(sprite, "interaction_margin", 48)
            in_range = self.player.rect.colliderect(
                sprite.rect.inflate(margin, margin)
            )
            sprite.notify_proximity(in_range)
            if in_range:
                self._show_interact_prompt = True

    def _resolve_sit_animation_paths(self, seat):
        cfg = getattr(seat, "env_config", None) or {}
        sit_cfg = cfg.get("sit_animations")
        if not isinstance(sit_cfg, dict):
            return {}
        out = {}
        tmx_folder = getattr(self.layout_manager, "tmx_folder", None)
        for key in ("sit_down", "sit_idle", "sit_up"):
            raw = sit_cfg.get(key)
            if not raw:
                continue
            resolved = resolve_env_interactable_path(str(raw).strip(), tmx_folder)
            if resolved:
                out[key] = resolved
        return out

    def _sit_on_seat(self, seat):
        player = self.player
        if not hasattr(player, "begin_seated_interaction"):
            return False
        if player.status == "sit_up":
            return False
        anchor_world = seat.get_seat_anchor() if hasattr(seat, "get_seat_anchor") else seat.rect.midbottom
        player_offset = getattr(seat, "player_offset", (0, 0))
        sit_paths = self._resolve_sit_animation_paths(seat)
        player.begin_seated_interaction(
            seat_obj=seat,
            anchor_world=anchor_world,
            player_offset=player_offset,
            sit_paths=sit_paths,
        )
        if hasattr(self, "rts_session"):
            self.rts_session.enter(throne=seat)
        return True

    def _stand_from_seat(self):
        player = self.player
        if getattr(player, "status", "") == "sit_up":
            return True
        if getattr(player, "seated_object", None) is None and not getattr(player, "status", "").startswith("sit_"):
            return False
        if hasattr(player, "begin_stand_from_seat"):
            player.begin_stand_from_seat()
            return True
        return False

    def _draw_interact_prompt(self):
        if not getattr(self, "_show_interact_prompt", False):
            return
        if getattr(self, "game_paused", False) or self.inventory_open:
            return
        font = pygame.font.Font(None, 28)
        text = font.render("[Space] Interact", True, (240, 240, 240))
        rect = text.get_rect()
        # Above draw_belt_hud (slots ~H-54..H-18 plus slot labels)
        rect.midbottom = (
            self.display_surface.get_width() // 2,
            self.display_surface.get_height() - 80,
        )
        self.display_surface.blit(text, rect)

    def try_interact_nearby_environment(self):
        if not self.input_manager.is_key_just_pressed(pygame.K_SPACE):
            return False
        if getattr(self, "game_paused", False):
            return False
        if getattr(self, "inventory_open", False):
            return False
        rts_session = getattr(self, "rts_session", None)
        if rts_session is not None and rts_session.is_active():
            rts_session.exit(request_stand=True)
            return True
        if self._stand_from_seat():
            return True
        lm = self.layout_manager
        env = getattr(lm, "environment_interactables", None)
        if not env:
            return False
        for obj in list(env):
            if getattr(obj, "opened", False):
                continue
            margin = getattr(obj, "interaction_margin", 48)
            if not self.player.rect.colliderect(obj.rect.inflate(margin, margin)):
                continue
            kind = str(getattr(obj, "kind", "loot_container")).strip().lower()
            if kind == "loot_container":
                self._open_loot_container(obj)
                return True
            if kind == "seat":
                return self._sit_on_seat(obj)
            _game_flow_log.debug(
                "env interactable kind=%r has no handler yet", kind
            )
            continue
        return False

    def try_open_nearby_chest(self):
        return self.try_interact_nearby_environment()

    def _resolve_chest_asset_path(self, raw_path):
        from Support import resolve_env_interactable_path

        return resolve_env_interactable_path(
            raw_path, getattr(self.layout_manager, "tmx_folder", None)
        )

    def _scale_chest_surface(self, chest, surf):
        """Match open-animation / static open art to TMX-scaled hit sprite size."""
        ds = getattr(chest, "display_size", None)
        if not ds or len(ds) < 2:
            return surf
        w, h = int(ds[0]), int(ds[1])
        if w <= 0 or h <= 0:
            return surf
        if surf.get_width() == w and surf.get_height() == h:
            return surf
        return pygame.transform.scale(surf, (w, h))

    def _apply_loot_container_open_visual(self, chest, center, cx, bottom):
        open_anim = getattr(chest, "open_animation_path", None)
        image_open = getattr(chest, "image_open_path", None)

        path_anim = self._resolve_chest_asset_path(open_anim) if open_anim else None
        path_img = self._resolve_chest_asset_path(image_open) if image_open else None
        final_surface = None
        anchor_midbottom = (cx, bottom)

        if path_img and os.path.isfile(path_img):
            final_surface = pygame.image.load(path_img).convert_alpha()
            final_surface = self._scale_chest_surface(chest, final_surface)

        if path_anim and os.path.isdir(path_anim):
            frames = import_folder(path_anim)
            ds = getattr(chest, "display_size", None)
            if frames and ds and len(ds) >= 2:
                w, h = int(ds[0]), int(ds[1])
                if w > 0 and h > 0:
                    frames = [
                        pygame.transform.scale(f, (w, h))
                        if f.get_width() != w or f.get_height() != h
                        else f
                        for f in frames
                    ]
            if not frames:
                _game_flow_log.debug(
                    "open animation folder empty or unreadable: %s", path_anim
                )
            if frames:
                if hasattr(chest, "start_open_animation"):
                    chest.start_open_animation(
                        frames,
                        final_surface=final_surface,
                        anchor_midbottom=anchor_midbottom,
                    )
                else:
                    fallback = final_surface if final_surface is not None else frames[-1]
                    chest.image = fallback
                    chest.mask = pygame.mask.from_surface(fallback)
                    chest.rect = fallback.get_rect(midbottom=anchor_midbottom)
                return
        if final_surface is not None:
            if hasattr(chest, "start_open_animation"):
                chest.start_open_animation(
                    [],
                    final_surface=final_surface,
                    anchor_midbottom=anchor_midbottom,
                )
            else:
                chest.image = final_surface
                chest.mask = pygame.mask.from_surface(final_surface)
                chest.rect = final_surface.get_rect(midbottom=anchor_midbottom)

    def _open_loot_container(self, chest):
        if hasattr(chest, "prepare_for_open"):
            chest.prepare_for_open()
        chest.opened = True
        lm = self.layout_manager
        if chest in lm.environment_interactables:
            lm.environment_interactables.remove(chest)
        center = chest.rect.center
        bottom = chest.rect.bottom
        cx = chest.rect.centerx

        drop_info = getattr(chest, "loot_info", None) or {}
        profile = getattr(chest, "profile_id", "") or "?"

        _game_flow_log.debug(
            "Chest open: profile=%r resolved loot_info=%s",
            profile,
            drop_info,
        )

        item_tuples = resolve_loot_table(drop_info)
        rolled_ids = [i for i, _ in item_tuples]
        _game_flow_log.debug(
            "Chest resolve_loot_table profile=%r count=%d item_ids=%s",
            profile,
            len(item_tuples),
            rolled_ids,
        )

        spawned_ids = []
        unknown_ids = []
        for item_id, _q in item_tuples:
            base = self.item_spawner.item_mapping.get(item_id)
            if not base:
                unknown_ids.append(item_id)
                continue
            cfg = copy.deepcopy(base)
            pos = [center[0] + random.randint(-24, 24), center[1] + random.randint(-16, 16)]
            item = self.item_spawner.create_item(cfg, pos)
            lm.add_item_visual(item)
            spawned_ids.append(item_id)

        if unknown_ids:
            _game_flow_log.warning(
                "Chest open profile=%r: no item_mapping for item_id(s) %s",
                profile,
                unknown_ids,
            )

        gold_amt = resolve_gold_drop(drop_info, random)
        gold_spawned = None
        if gold_amt and gold_amt > 0:
            base = self.item_spawner.item_mapping.get("gold_coin")
            if base:
                cfg = copy.deepcopy(base)
                cfg["effect"] = {"gold": int(gold_amt)}
                pos = [center[0] + random.randint(-24, 24), center[1] + random.randint(-16, 16)]
                item = self.item_spawner.create_item(cfg, pos)
                lm.add_item_visual(item)
                gold_spawned = int(gold_amt)
            else:
                _game_flow_log.warning(
                    "Chest open profile=%r: gold_drop rolled %s but gold_coin missing from item_mapping",
                    profile,
                    gold_amt,
                )
        _game_flow_log.debug(
            "Chest resolve_gold_drop profile=%r amount_resolved=%s amount_spawned=%s",
            profile,
            gold_amt,
            gold_spawned,
        )

        if not spawned_ids and gold_spawned is None:
            _game_flow_log.info(
                "Chest opened with empty loot table (profile=%r rolled_item_ids=%s)",
                profile,
                rolled_ids,
            )
        else:
            _game_flow_log.debug(
                "Chest open result profile=%r spawned_items=%s gold=%s",
                profile,
                spawned_ids,
                gold_spawned,
            )

        self._apply_loot_container_open_visual(chest, center, cx, bottom)

    def get_level_up_threshold(self, level):
        return 1000 * level ** 2

    def check_level_up(self):
        threshold = self.get_level_up_threshold(self.player.power_level)
        if self.player.exp >= threshold:
            self.player.power_level += 1
            self.player.exp = 0  # Reset experience
            # Increase player stats here, if desired
            self.trigger_level_up_effect()
            self.player.player_config.add_remaining_points(20)
            self.toggle_player_config()


    def trigger_level_up_effect(self):
        # Example using an existing animation player
        # You might need to adjust the path and animation specifics
        animation_frames = import_folder('../Graphics/LevelUpAnimation')
        animation_position = self.player.rect.center 
        animation_speed = 30 
        self.layout_manager.trigger_animation(animation_frames, animation_position, animation_speed)


    def restore_persistent_enemies(self,layout_path):
        if layout_path in self.persistent_enemy_data:
            for enemy_state in self.persistent_enemy_data[layout_path]:
                self.spawner.restore_enemy(enemy_state)



    def handle_item_collection(self):
        """Check for collisions between the player and items to handle item collection."""
        for visual_item in [sprite for sprite in self.layout_manager.visible_sprites if isinstance(sprite, ItemVisual)]:
            if self.player.rect.colliderect(visual_item.rect):
                ok = self.player.pickup_item(visual_item.item)
                if ok:
                    self.item_spawner.remove_item(visual_item.item)
                    visual_item.kill()
                else:
                    visual_item.start_reject_shake()

    def check_enemy_deaths(self):
        dead_enemies = [enemy for enemy in self.spawner.enemies if enemy.is_dead()]
        
        #print("dead_enemies")
        #print(len(dead_enemies))
        
        processed_enemies = [] 
        #print(f"DEAD ENEMIES : {dead_enemies}")
        for enemy in dead_enemies:
            dropped_items = self.item_spawner.drop_from_enemy(enemy)
            #print(dropped_item_info)
            if dropped_items:
                # Convert the item drop position to map coordinates if necessary
                drop_position = (enemy.rect.x, enemy.rect.y)
                #self.layout_manager.place_items_on_map([dropped_item_info]) # Place items on map not used
     
                #print(f"ITEMS OUTPUTTED BY SPAWNER - DROPPED  ITEMS: {dropped_items}")
                pos_offset_counter = 0
                
                for item in dropped_items:
                    #item.pos[0][0] = drop_position[0] + pos_offset_counter*random.randint(12,40)
                    #item.pos[0][1] = drop_position[1] + pos_offset_counter*random.randint(12,40)
                    self.layout_manager.add_item_visual(item)
                    pos_offset_counter += 1

            processed_enemies.append(enemy)
        # Remove processed enemies from the list of enemies managed by the spawner
        #print("processed enemies")
        #print(len(processed_enemies))
        #print("number enemies in spawner")
        #print(len(self.spawner.enemies))
        for enemy in processed_enemies:
            self.spawner.enemies.remove(enemy)
        #print("number enemies in spawner")
        #print(len(self.spawner.enemies))

    def save_enemy_states(self):
        # Save the state of all persistent enemies
        self.persistent_enemy_data[self.current_layout] = [
            {
                'type': enemy.type,
                'position': enemy.rect.topleft,
                'health': enemy.health
            }
            for enemy in self.spawner.enemies if enemy.persistent
        ]


    def check_triggers(self):
        
        current_time = pygame.time.get_ticks()
        if self.last_trigger_time is not None and current_time - self.last_trigger_time < self.trigger_cooldown:
            return  # Still in cooldown period, do not activate triggers

        for trigger in self.layout_manager.trigger_sprites:
            if self.player.rect.colliderect(trigger.rect):
                new_player_position = trigger.new_player_position

                #print("new position")
                #print(new_player_position)
                #print(new_player_position[0])
                #print(new_player_position[1])
                #print(" new version ")
                #print([pos * TILESIZE for pos in new_player_position])


                new_player_position[0] = new_player_position[0]*TILESIZE
                new_player_position[1] = new_player_position[1]*TILESIZE

                #print("old version")
                #print( new_player_position )
                 # Reset InputManager state
                self.input_manager.reset()
                self.last_trigger_time = current_time
                #print(f"trigger path : {trigger.destination_layout}")
                #print(f" new player position : {trigger.new_player_position}")
                
                
           
                
                
                
                self.start_map(input_manager = self.input_manager,
                               selected_player_info_dir = self.selected_player_info_dir,
                               layouts_dir = trigger.destination_layout,
                               display_surface=self.display_surface,
                               layout_manager=self.layout_manager,
                               Player = self.player,
                               restart = True,
                               player_position = new_player_position)
                
                ## So , the issue seems to be that i run level.run in main, in level.run, i check triggers, but this stops the game_loop,
                #       although, i does not, i guess as expected, what is does is is keep going but have display_surfce = None.
                
                
                #self.layout_manager.spawner.restore_persistent_enemies(trigger.destination_layout) # Done with callback.
                
                

    def _full_dev_reload(self):
        """Full dev reload: save state, restart process. Settings and all code reload."""
        level_number = LAYOUT_TO_LEVEL.get(self.layouts_dir, self.level_number or 6)
        dev_state = {
            'level_number': level_number,
            'layouts_dir': self.layouts_dir,
            'player_position': list(self.player.rect.topleft),
            'player_info_dir': self.selected_player_info_dir,
            'player_stats': self.player_base_stats,
        }
        with open(DEV_STATE_PATH, 'w') as f:
            json.dump(dev_state, f, indent=2)
        pygame.quit()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def save_enemy_states(self, current_layout):
        self.persistent_enemy_data[current_layout] = [{'type': enemy.type, 'position': enemy.rect.topleft, 'health': enemy.health} for enemy in self.spawner.enemies if enemy.persistent]




    def create_attack(self):
        self.current_attack = Weapon(self.player, [self.layout_manager.visible_sprites, self.attack_sprites])

    def create_magic(self, style, strength, cost):
        #print("Magic cost")
        #print(cost)
        # Magic creation logic here
        if style == "heal":
            self.magic_player.heal(self.player, strength, cost, [self.layout_manager.visible_sprites])
        elif style == "flame":
            self.magic_player.flame(self.player, cost, [self.layout_manager.visible_sprites, self.attack_sprites])
        if style == 'ice_ball':
            particle = self.magic_player.ice_ball2(self.player, cost, [self.layout_manager.visible_sprites, self.attack_sprites], self.layout_manager.entity_quad_tree)
            # Register particle in the dictionary
            self.particle_dict[id(particle)] = particle
       
        
    def redirect_projectile_callback(self, projectile_id, new_direction):
        projectile = self.particle_dict.get(projectile_id)
        if projectile:
            projectile.movement = new_direction * projectile.movement.length()
            projectile.distance_moved = 0
            # Add the particle to the enemy_attack_sprites group
            if not projectile.groups().__contains__(self.enemy_attack_sprites):
                self.enemy_attack_sprites.add(projectile)
            owner_team = getattr(getattr(projectile, "owner", None), "team_id", None)
            projectile.source_team = owner_team if owner_team is not None else "enemy"
            projectile.source_kind = "enemy_projectile"
            projectile.attack_type = "magic"
            projectile.owner = None
            
                    
                
     
    def create_evasion(self, style, direction):
        # Callback to handle particle creation on each movement step
        # def handle_slide_particles(player):
        #     current_tile_center = (
        #         (player.rect.centerx // TILESIZE) * TILESIZE + TILESIZE // 2,
        #         (player.rect.centery // TILESIZE) * TILESIZE + TILESIZE // 2
        #     )
        #     self.animation_player.create_particles("slide_effect", current_tile_center, self.player.groups())
            
        # Initiate the slide with the particle handling callback
        if style == 'slide':
            self.evasion_player.slide(self.player, direction)#, handle_slide_particles)
        if style == 'create_ice_clone':
            self.evasion_player.create_ice_clone( self.player, effect_type='freeze' , radius = 5)# TODO radiu should be a player attribute right ? player.evasion attribute 

    def destroy_attack(self):
        if self.current_attack:
            self.current_attack.kill()
        self.current_attack = None

    def player_attack_logic(self):

        
        # TODO : implement quadtree ? its not particularly heavy part of the code...
        #      : implement mask collision
        #print("attack_sprites")
        #print(self.attack_sprites)
        if self.attack_sprites:

            
            for attack_sprite in self.attack_sprites:
                #print("attack sprite position")
                #print( attack_sprite.rect.left )
                #print(  attack_sprite.rect.width)
                #print(  attack_sprite.rect.height)
                collision_sprites = pygame.sprite.spritecollide(attack_sprite, self.attackable_sprites, False)
                if collision_sprites:
                    for target_sprite in collision_sprites:
                        if target_sprite is self.player:
                            continue
                        interaction_kind = getattr(attack_sprite, "interaction_kind", "damage")
                        source_team = getattr(
                            attack_sprite,
                            "source_team",
                            getattr(self.player, "team_id", "player"),
                        )
                        target_team = getattr(target_sprite, "team_id", None)
                        if not self.interaction_resolver.can_potentially_affect(
                            source_team=source_team,
                            target_team=target_team,
                            kind=interaction_kind,
                        ):
                            continue
                        attack_type = getattr(
                            attack_sprite,
                            "attack_type",
                            "weapon" if attack_sprite.sprite_type == "weapon" else "magic",
                        )
                        ctx = InteractionContext(
                            kind=interaction_kind,
                            source_kind=getattr(attack_sprite, "source_kind", "player_attack"),
                            source=getattr(attack_sprite, "owner", self.player),
                            owner=getattr(attack_sprite, "owner", self.player),
                            source_team=source_team,
                            target=target_sprite,
                            amount=getattr(attack_sprite, "amount", None),
                            attack_type=attack_type,
                            tags=set(getattr(attack_sprite, "tags", set())),
                        )
                        self.interaction_resolver.apply(ctx)


    
    def enemy_projectile_logic(self):

        if self.enemy_attack_sprites:
            for enemy_attack_sprite in self.enemy_attack_sprites:
                projectile_owner = getattr(enemy_attack_sprite, "owner", None)
                projectile_owner_team = getattr(projectile_owner, "team_id", None)
                source_team = getattr(enemy_attack_sprite, "source_team", "enemy")
                interaction_kind = getattr(enemy_attack_sprite, "interaction_kind", "damage")
                _combat_log.debug(
                    "enemy_projectile scan sprite_id=%s owner_id=%s owner_team=%r source_team=%r kind=%r pos=%r",
                    id(enemy_attack_sprite),
                    id(projectile_owner) if projectile_owner is not None else None,
                    projectile_owner_team,
                    source_team,
                    interaction_kind,
                    getattr(getattr(enemy_attack_sprite, "rect", None), "center", None),
                )
                collision_sprites = pygame.sprite.spritecollide(enemy_attack_sprite, self.attackable_sprites, False)
                _combat_log.debug(
                    "enemy_projectile candidates sprite_id=%s candidate_count=%d target_mode=attackable_group",
                    id(enemy_attack_sprite),
                    len(collision_sprites),
                )
                if collision_sprites:
                    for target_sprite in collision_sprites:
                        if target_sprite is projectile_owner or target_sprite is enemy_attack_sprite:
                            _combat_log.debug(
                                "enemy_projectile skip sprite_id=%s target_id=%s reason=owner_or_self",
                                id(enemy_attack_sprite),
                                id(target_sprite),
                            )
                            continue
                        target_team = getattr(target_sprite, "team_id", None)
                        prefilter_allowed = self.interaction_resolver.can_potentially_affect(
                            source_team=source_team,
                            target_team=target_team,
                            kind=interaction_kind,
                        )
                        _combat_log.debug(
                            "enemy_projectile prefilter sprite_id=%s target_id=%s target_team=%r allowed=%s",
                            id(enemy_attack_sprite),
                            id(target_sprite),
                            target_team,
                            prefilter_allowed,
                        )
                        if not prefilter_allowed:
                            continue
                        ctx = InteractionContext(
                            kind=interaction_kind,
                            source_kind=getattr(enemy_attack_sprite, "source_kind", "enemy_projectile"),
                            source=getattr(enemy_attack_sprite, "owner", enemy_attack_sprite),
                            owner=getattr(enemy_attack_sprite, "owner", None),
                            source_team=source_team,
                            target=target_sprite,
                            amount=getattr(enemy_attack_sprite, "amount", None),
                            attack_type=getattr(enemy_attack_sprite, "attack_type", "magic"),
                            tags=set(getattr(enemy_attack_sprite, "tags", set())),
                        )
                        resolved = self.interaction_resolver.apply(ctx)
                        _combat_log.debug(
                            "enemy_projectile apply sprite_id=%s target_id=%s target_team=%r resolved=%s amount=%r attack_type=%r",
                            id(enemy_attack_sprite),
                            id(target_sprite),
                            target_team,
                            resolved,
                            getattr(enemy_attack_sprite, "amount", 10),
                            getattr(enemy_attack_sprite, "attack_type", "magic"),
                        )

    def _safe_number(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _resolve_projectile_damage_payload(self, owner, projectile_type=None, base_amount=None):
        base_damage = base_amount
        combat_config = {}
        if owner is not None:
            owner_config = getattr(owner, "combat_config", None)
            if isinstance(owner_config, dict):
                combat_config = owner_config
        if base_damage is None:
            ranged_attacks = combat_config.get("ranged_attacks", [])
            if isinstance(ranged_attacks, list):
                for attack in ranged_attacks:
                    if not isinstance(attack, dict):
                        continue
                    if projectile_type is not None and attack.get("type") != projectile_type:
                        continue
                    candidate = attack.get("damage")
                    if candidate is not None:
                        base_damage = candidate
                        break
        if base_damage is None:
            base_damage = combat_config.get("default_ranged_damage")
        if base_damage is None:
            return None
        multiplier = self._safe_number(combat_config.get("projectile_damage_multiplier", 1.0), 1.0)
        bonus = self._safe_number(combat_config.get("projectile_damage_bonus", 0.0), 0.0)
        if owner is not None:
            getter_multiplier = getattr(owner, "get_projectile_damage_multiplier", None)
            if callable(getter_multiplier):
                multiplier *= self._safe_number(getter_multiplier(), 1.0)
            getter_bonus = getattr(owner, "get_projectile_damage_bonus", None)
            if callable(getter_bonus):
                bonus += self._safe_number(getter_bonus(), 0.0)
            multiplier *= self._safe_number(getattr(owner, "projectile_damage_multiplier", 1.0), 1.0)
            bonus += self._safe_number(getattr(owner, "projectile_damage_bonus", 0.0), 0.0)
        resolved_damage = int(round(self._safe_number(base_damage, 0.0) * multiplier + bonus))
        return max(0, resolved_damage)

    def emit_enemy_melee_hit(self, enemy, target, attack):
        amount = None
        attack_type = "melee"
        if isinstance(attack, dict):
            amount = attack.get("damage")
            attack_type = attack.get("type", "melee")
        source_team = getattr(enemy, "team_id", "enemy")
        target_team = getattr(target, "team_id", None)
        if not self.interaction_resolver.can_potentially_affect(
            source_team=source_team,
            target_team=target_team,
            kind="damage",
        ):
            return
        ctx = InteractionContext(
            kind="damage",
            source_kind="enemy_melee",
            source=enemy,
            owner=enemy,
            source_team=source_team,
            target=target,
            amount=amount,
            attack_type=attack_type,
            tags={"enemy_melee"},
        )
        self.interaction_resolver.apply(ctx)




### Single function to do all damage evaluation ( Not currently being used )
    
    def evaluate_damage(self):
        for team in self.teams:
            self.evaluate_team_damage(team)

    def evaluate_team_damage(team):
        
        
        
        """
        So i need to change the format of sprite groups
        
        a dictionary that keeps all the sprites, in teams
        
        Some attacks need to be able to hurt everybody (currently all attack sprites can hurt anyone)
        
        The Player needs to be in his own team, summons will then go in this team too.
        
        
        WL:
        In the combat streategy, the melee attack just damages directly, i actually need to create the attack
        sprite
        
        For player melee, i think an attack sprite is created.....for player, it creates an attack sprite, right?
        
        
        im not sure what is happening, i import Weapon and then create_attack adds an attack to attaack
        sprites, when there is no weapon, im not sure what happens. 
        
        okokok so the Weapon is actually a sprite and it is created as an attack sprite,
        in terms of not having a weapon, I'm not sure how it works.'
        
        ok, even without weapon, an attack sprite is created
        
        WLL: will do some tests on the size of the attack sprite that is created,
             i just want to understand how the non weapon attack sprite is created
             
             for weapons, do they need to collide with the weapon or anything on the player
             for non weapon, same.
             
             ok for weapon, it works quite well, for non weapon, its just a collision with some area in the
             direction that you are clicking , which is wierd, it should be a mask collision with the
             players weapon.
        
            It seems there are no mask collisions anyway, just for bumping and that.
            
            Yea, no, its just the entire square that it can collide with.in terms of being hit myself, 
            i dont think thats true though. Yea, its the same for me, no mask collision
            
            WLL: 
                1.do the mask collision first 
                WLL
                Its the weapon that is the sprite, the collision happens: player_attack_logic
                
                2.check how no weapon attack sprite is created ( i think its just in weapon )
                3. Test the general get damage function for enemy melee ( remove direct damage from
                                                                          combat strat, make an attack sprite)
        
        
        """
        
        
        # Damage from enemy teams
        enemy_teams = team.enemy_teams
        
        for enemy_team in enemy_teams:
            for attack_sprite in self.attack_sprites[team]:
                collision_sprites = pygame.sprite.spritecollide( attack_sprite, self.sprites[team], False)
                for target_sprite in collision_sprites:
                    attack_type = 'physical' if attack_sprite.sprite_type == 'weapon' else 'magic'
                    target_sprite.get_damage( attack_sprite, attack_type )
            
        # Possible neutral/friendly damage

        for attack_sprite in self.attack_sprites["damage_all"]:
            collision_sprites = pygame.sprite.spritecollide( attack_sprite, self.sprites[team], False)
            for target_sprite in collision_sprites:
                attack_type = 'physical' if attack_sprite.sprite_type == 'weapon' else 'magic'
                target_sprite.get_damage( attack_sprite, attack_type )


  

    def damage_player(self, amount, attack_type=None):
        
        
        #print(f"made it to damage player , vulerable: {self.player.vulnerable}")
        #print(amount)
        
        if self.player.vulnerable:
            self.player.health -= amount
            self.player.vulnerable = False
            self.player.hurt_time = pygame.time.get_ticks()
            
            if attack_type:
                if attack_type != 'melee': ## TODO : a at the moment this is recieving attack type to do attack particles, 
                                                    # we do not have any attack particles for this so screw it.
                                                    
                    self.animation_player.create_particles(attack_type, self.player.rect.center, [self.layout_manager.visible_sprites])

    def trigger_death_particles(self, pos, particle_type):
        # Particle effect logic here
        self.animation_player.create_particles(particle_type, pos, [self.layout_manager.visible_sprites])

    def add_exp(self, amount):
        self.player.exp += amount
        self.check_level_up()


    def toggle_menu(self):
        self.game_paused = not self.game_paused
        self.upgrade_menu_open = not self.upgrade_menu_open

    def _seed_default_belt_if_needed(self):
        cfg = self.item_spawner.item_mapping.get("simple_belt")
        if not cfg or not getattr(self, "player", None):
            return
        inv = self.player.inventory
        wslot = inv.slots[inv.waist_slot_index]
        if wslot.item is not None:
            inv.sync_belt_from_waist()
            return
        cfg = copy.deepcopy(cfg)
        belt_item = self.item_spawner.create_item(cfg, [0, 0])
        wslot.item = belt_item
        wslot.quantity = 1
        inv.sync_belt_from_waist()

    def toggle_inventory(self):
        self.game_paused = not self.game_paused
        self.inventory_open = not self.inventory_open
        self.player.inventory.visible = self.inventory_open
        if not self.inventory_open:
            self.player.inventory.return_hand_to_backpack()
            self.player.inventory.sync_belt_from_waist()

    def notify_gold_pickup(self, amount):
        if amount <= 0:
            return
        if self.game_settings and getattr(self.game_settings, "gold_pickup_popup", True):
            self._gold_popup_amount = amount
            self._gold_popup_until_ms = pygame.time.get_ticks() + 1300

    def _draw_gold_pickup_popup(self):
        if pygame.time.get_ticks() >= getattr(self, "_gold_popup_until_ms", 0):
            return
        amt = getattr(self, "_gold_popup_amount", 0)
        if amt <= 0:
            return
        font = pygame.font.Font(None, 40)
        text = f"Gold +{amt}"
        surf = font.render(text, True, (255, 215, 0))
        shadow = font.render(text, True, (30, 22, 0))
        w, h = self.display_surface.get_size()
        x = (w - surf.get_width()) // 2
        y = int(h * 0.70)
        self.display_surface.blit(shadow, (x + 2, y + 2))
        self.display_surface.blit(surf, (x, y))

    def toggle_attack_selection(self):
        self.game_paused = not self.game_paused
        self.attack_selection_open = not self.attack_selection_open
        self.player.attack_selection.visible = self.attack_selection_open
        
    
    def toggle_player_config(self):
        self.game_paused = not self.game_paused
        self.player_config_open = not self.player_config_open
        self.player.player_config.visible = self.attack_selection_open # Dont think this is even being used.
        
    def update_player_stats(self): # TODO: bit messy in terms of calling player from level,,, i do interaction issues in level often but 
                                   # really this can be a player method, the only this is that the player config screen recieves level
                                   # so we call it from level as opposed to level.player....
        new_stats = self.player.player_config.final_stats 
        self.player.stats = new_stats
        
        # Define a method to get the direction vector from an angle
    def get_direction_from_angle(self, angle):
        # Convert angle to radians
        radians = math.radians(angle)
        # Calculate the x and y components of the direction vector
        direction_x = math.cos(radians)
        direction_y = -math.sin(radians)  # Negative sin because y-coordinates are flipped in pygame
        # Return the direction vector
        return pygame.math.Vector2(direction_x, direction_y)
    #@profile
    def fire_projectile(self, enemy_pos, target_pos, projectile_type, groups, owner=None, source_team=None, amount=None): ### groups not actually used, we pass level references to the groups explicitely below , regardles,, this could be confusing ISSUE
    
        # Calculate the angle to the target
        angle_to_target = self.calculate_angle(enemy_pos, target_pos)
        # Round the angle to the nearest multiple of 20 degrees
        rounded_angle = self.round_angle(angle_to_target)
        # Determine the direction vector based on the rounded angle
        direction = self.get_direction_from_angle(rounded_angle)
        resolved_owner = owner
        if resolved_owner is None and groups:
            for sprite in groups:
                if hasattr(sprite, "team_id"):
                    resolved_owner = sprite
                    break
        resolved_source_team = source_team
        if resolved_source_team is None:
            resolved_source_team = getattr(resolved_owner, "team_id", "enemy")
        resolved_amount = self._resolve_projectile_damage_payload(
            owner=resolved_owner,
            projectile_type=projectile_type,
            base_amount=amount,
        )
        _combat_log.debug(
            "enemy_projectile payload owner_id=%s projectile_type=%r base_amount=%r resolved_amount=%r source_team=%r",
            id(resolved_owner) if resolved_owner is not None else None,
            projectile_type,
            amount,
            resolved_amount,
            resolved_source_team,
        )
        # Invoke the method responsible for creating the projectile, passing in the direction
        self.animation_player.create_particles(animation_type = projectile_type,
                                               pos = enemy_pos,
                                               groups = [self.enemy_attack_sprites, 
                                                         self.layout_manager.visible_sprites],
                                               quadtree=self.layout_manager.entity_quad_tree,
                                               direction=direction*12,# TODO :actually controls speed, i need to unify how i do it in magic and here, two similar params
                                               is_moving = True,
                                               total_distance=1000,
                                               owner=resolved_owner,
                                               source_team=resolved_source_team,
                                               source_kind="enemy_projectile",
                                               attack_type="magic",
                                               amount=resolved_amount
                                               )


    def calculate_angle(self, source, target):
        dx = target[0] - source[0]
        dy = target[1] - source[1]
        return math.degrees(math.atan2(-dy, dx)) % 360  # Calculate angle in degrees

    # Define a method to round the angle to the nearest multiple of 20 degrees
    def round_angle(self, angle):
        return round(angle / 20) * 20  # Round to the nearest multiple of 20 degrees



    #@profile
    def run(self,dt):
 
        dt_real = dt   # dno what the dt divided by fps is .... some wierd desperate attempt to make something work..
        dt = dt / FPS
        dt = dt_real
        self.wind_timer += dt
        self.display_surface.fill((0, 0, 0)) 
        #print(FPS)
        #print(self.player.rect.center)
         
        self.check_triggers() # i guess i need to pass persist data ?  
        if self.input_manager.is_key_just_pressed(pygame.K_F5):
            self._full_dev_reload()
        if self.benchmark_runtime.enabled:
            if self.input_manager.is_key_just_pressed(pygame.K_F6):
                self._toggle_pushback_floor()
            if self.input_manager.is_key_just_pressed(pygame.K_F7):
                self._toggle_pushback_cap()
            if self.input_manager.is_key_just_pressed(pygame.K_F8):
                self._toggle_benchmark_backend()
        #print(self.player.rect.center)
        #print(self.layout_manager.player.rect.center)
        self.layout_manager.spawner.on_layout_update()
        if hasattr(self, "rts_world_sim"):
            self.rts_world_sim.tick(dt_real, self.rts_world_adapter)
        if hasattr(self, "rts_session"):
            self.rts_session.update(dt_real)
        if getattr(self, "_rts_validation_driver", None) is not None:
            if self._rts_validation_driver.tick(self, dt_real):
                RTS_VALIDATION_RUNTIME.write_results()
                code = 0 if RTS_VALIDATION_RUNTIME.all_passed else 1
                RTS_VALIDATION_RUNTIME.request_shutdown(code)
                pygame.event.post(pygame.event.Event(pygame.QUIT))
        camera_focus = (
            self.rts_session.camera_focus()
            if getattr(self, "rts_session", None) is not None and self.rts_session.is_active()
            else self.player
        )
        #print(f"\n\n after layout update {self.player.rect.x}\n\n")
        #self.layout_manager.visible_sprites.custom_draw(self.player,dt, self.weather.weather_intensity, self.weather.light_level)
       #print(f"\n\n after after custom draw {self.player.rect.x}\n\n")
        
        

        if self.game_paused:
            if self.upgrade_menu_open:
                self.upgrade.display()
            elif self.inventory_open:
                self.player.inventory.display(self.display_surface)
                self.player.inventory.input()
                for sprite in self.layout_manager.visible_sprites:
                    if isinstance(sprite, ItemVisual):
                        sprite.update(dt)
            elif self.attack_selection_open:
                self.player.attack_selection.display(self.display_surface)
                self.player.attack_selection.input()
                self.player.update_derived_attributes()
            elif self.player_config_open:
                
                self.player.player_config.draw(self.display_surface) # TODO: align naming convensions of these screens.
                self.player.player_config.handle_events(self)
                #self.player.stats = self.player.player_config.final_stats
                
        else:
            
            
            if self.layout_manager.daytime_layout:
                if self.game_settings:
                    self.weather.time_speed_multiplier = self.game_settings.environment_speed
                self.layout_manager.visible_sprites.custom_draw(
                    self.player,
                    dt,
                    self.weather.weather_intensity,
                    self.weather.light_level,
                    camera_focus=camera_focus,
                )
                self.weather.update(dt)
                self.weather_overlay.set_weather(self.weather.weather_type,
                                                 self.weather.weather_intensity,
                                                 self.weather.wind_direction)
                self.layout_manager.daytime_brightness_overlay.set_time_of_day( self.weather.current_time )
                self.layout_manager.daytime_brightness_overlay.draw()
                if self.weather.weather_type != 'clear':
                    self.weather_overlay.update(dt) 
                    self.weather_overlay.draw()
                
                wind_force = self.weather.calculate_wind_force()
                
                # TODO: Should be placed in the Player, not level.
                #### Player brightness circles / vision at night
                   
                                
                # TODO: atleast refactor this, it seems that it needs OFFSET from camera group so level is not a terrible place for it
                #       ideally find a way to have it in torch and player as opposed to here.
                # Define brightness settings for Torch 
                # torch_brightness_radius = 220
                # num_circles = 6  
                # #torch_brightness_factor = 0
                
                               
                                # Player brightness settings
                self.brightness_radius = 240
                num_circles = 6  # Adjust as needed
                
                # Determine brightness factor based on weather conditions
                if (self.weather.current_time > 18 and self.weather.current_time <= 20) or (self.weather.current_time <= 10 and self.weather.current_time > 9):
                    brightness_factor = 0.008
                elif (self.weather.current_time > 20 and self.weather.current_time <= 22) or (self.weather.current_time <= 9 and self.weather.current_time > 7):
                    brightness_factor = 0.009
                elif self.weather.current_time > 22 or self.weather.current_time <= 7:
                    brightness_factor = 0.012
                else:
                    brightness_factor = 0.007
                
                # Create a surface for the brightness effect
                brightness_surface = pygame.Surface(self.display_surface.get_size(), pygame.SRCALPHA)
                brightness_surface.fill((0, 0, 0, 0))  # Fill with transparent
                
                # Player position
                center_x = self.display_surface.get_width() // 2
                center_y = self.display_surface.get_height() // 2
                
                # Helper function to calculate distance between two points
                def calculate_distance(x1, y1, x2, y2):
                    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)
                
                # Draw brightness for player and torches on a per-circle basis
                for i in range(num_circles):
                    radius = self.brightness_radius * (1 / ((i + 1) ** 0.70))
                    player_brightness = brightness_factor * (1.58 ** i)  # Player brightness for this circle
                
                    # Draw the player circle
                    pygame.draw.circle(brightness_surface,
                                       (255 * player_brightness, 255 * player_brightness, 255 * player_brightness, 255),
                                       (center_x, center_y), radius)
                
                    # Handle torch circles
                    for sprite in self.layout_manager.visible_sprites.sprites():
                        if isinstance(sprite, Torch):
                            torch_center_x = sprite.rect.centerx - self.layout_manager.visible_sprites.offset.x
                            torch_center_y = sprite.rect.centery - self.layout_manager.visible_sprites.offset.y
                
                            # Calculate torch brightness for this circle
                            torch_brightness = brightness_factor * (1.58 ** i)
                
                            # Check if the torch circle overlaps with the player's circle
                            distance_to_player = calculate_distance(torch_center_x, torch_center_y, center_x, center_y)
                
                            if distance_to_player < (radius):  # Overlap detected
                                # Compare the brightness of the torch and the player for this circle
                                if torch_brightness > player_brightness:
                                    # Torch is brighter, draw the torch circle
                                    pygame.draw.circle(brightness_surface,
                                                       (255 * torch_brightness, 255 * torch_brightness, 255 * torch_brightness, 255),
                                                       (torch_center_x, torch_center_y), radius)
                                else:
                                    # Player is brighter, skip drawing the torch circle in this region
                                    continue
                            else:
                                # No overlap, draw the torch circle normally
                                pygame.draw.circle(brightness_surface,
                                                   (255 * torch_brightness, 255 * torch_brightness, 255 * torch_brightness, 255),
                                                   (torch_center_x, torch_center_y), radius)
                
                # Now we need to combine the brightness effects
                self.display_surface.blit(brightness_surface, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

               
                
               
                    
        
                self.layout_manager.visible_sprites.update_parallel( obstruction_quad_tree = self.layout_manager.obstacle_quad_tree,
                                                                     entity_quad_tree = self.layout_manager.entity_quad_tree,
                                                                     dt=dt,
                                                                     weather = self.weather, 
                                                                     wind_force=wind_force )
                    
                
                #print("new quad tree item mappings:")
                #print(self.layout_manager.entity_quad_tree.manager.item_mapping)
            else:
                #print("new quad tree item mappings:")
                #print(self.layout_manager.entity_quad_tree.manager.item_mapping)
                self.layout_manager.visible_sprites.update_parallel( obstruction_quad_tree = self.layout_manager.obstacle_quad_tree,
                                                                     entity_quad_tree = self.layout_manager.entity_quad_tree,
                                                                     dt=dt,
                                                                     weather = self.weather,
                                                                     wind_force = None )
                
                # Non-daytime layouts normally pass 0 wind (no grass sway). Grass benchmarks need a fixed strong sway so
                # legacy_tile vs shared_patch are meaningful (see BENCHMARK_GRASS_SWAY_INTENSITY / PRCH_BENCHMARK_GRASS_SWAY_INTENSITY).
                _grass_sway = (
                    self.benchmark_runtime.grass_sway_intensity
                    if (
                        self.benchmark_runtime.enabled
                        and self.benchmark_runtime.grass_benchmark_enabled
                    )
                    else 0
                )
                self.layout_manager.visible_sprites.custom_draw(
                    self.player, dt, _grass_sway, 0.5, camera_focus=camera_focus
                )
            #self.layout_manager.update_weather(self.weather)
            
            self.layout_manager.spawner.handle_spawn_areas( self.player,dt_real )        
            # Check for and update enemy sprites specifically
            self.ui.display(self.player)
            self._draw_benchmark_overlay()
            self._draw_rts_validation_overlay()

            self._frame_number += 1
            entity_id_map = {
                s.id: s
                for s in self.layout_manager.visible_sprites.sprites()
                if hasattr(s, "id")
            }
            for sprite in self.layout_manager.visible_sprites.sprites():
                # debug
                # if hasattr(sprite, 'frozen'):
                #     if hasattr(sprite, 'frozen_image'):
                #         pygame.display.get_surface().blit(sprite.frozen_image, (100, 100))


                if hasattr(sprite, 'enemy_update'):
                    sprite.enemy_update(
                        None,
                        self.layout_manager.entity_quad_tree,
                        frame_number=self._frame_number,
                        entity_id_map=entity_id_map,
                    )
                elif isinstance( sprite, Trap):
                    enemies_in_range = self.check_trap_triggers(sprite)
                    # Prolly pass  enemies to activate to freeze them n that.
                    if len(enemies_in_range) > 0:
                        sprite.activate()
                
                # Check for effect collisions (separate from physics collisions)
                if isinstance(sprite, Entity):
                    sprite.check_effects(
                        self.layout_manager.effect_quad_trees,
                        self.layout_manager.effect_cell_grid,
                    )
                    sprite.apply_environmental_damage(dt)
                       
             
            spawned_items = self.item_spawner.update()

            #print(f"In level game loop, spawned items from item spawner update : {spawned_items}")

            for item in spawned_items:
                #print(f"\n\nATTEMPTING TO SPAWN FISH \n\n item:{item}\n id:{item.item_id}\n pos:{item.pos}")
                self.layout_manager.add_item_visual(item)            
            
            self.check_enemy_deaths()
            self.handle_item_collection()
            self._update_loot_container_proximity()
            #self.layout_manager.visible_sprites.enemy_update(self.player)  
           #print(f"\n\n after PRE ATTACK {self.player.rect.x}\n\n")
            self.player_attack_logic()
            self.enemy_projectile_logic()

        if self.benchmark_runtime.enabled and self.benchmark_runtime.metrics_enabled:
            if self.benchmark_runtime.case_phase == "warmup" and self.benchmark_runtime.warmup_elapsed():
                self.benchmark_runtime.begin_run(self.benchmark_runtime.run_label)
                print(
                    f"[BENCH] Measurement started label={self.benchmark_runtime.run_label} "
                    f"seconds={self.benchmark_runtime.auto_run_seconds} "
                    f"grid_cell_size={self.benchmark_runtime.grid_cell_size}",
                    flush=True,
                )

            if self.benchmark_runtime.case_phase == "measure":
                self.benchmark_runtime.metrics.record_frame(dt_real)
                self.benchmark_runtime.maybe_log_metrics()
                if self.benchmark_runtime.should_auto_stop() and not self._benchmark_summary_written:
                    row = self.benchmark_runtime.write_summary_row()
                    self.benchmark_runtime.case_phase = "complete"
                    print(
                        f"[BENCH] Case complete label={row['run_label']} "
                        f"avg_fps={row['avg_fps']:.2f} p95_ms={row['p95_frame_ms']:.2f} "
                        f"queries={int(row['broadphase_queries'])} candidates={int(row['candidate_collisions'])}",
                        flush=True,
                    )
                    if self.benchmark_runtime.matrix_enabled:
                        self._start_next_benchmark_case()
                    else:
                        self._benchmark_summary_written = True
                        pygame.event.post(pygame.event.Event(pygame.QUIT))

        self.save_enemy_states(self.current_layout)  # mkght be a big inefficiency
        self.layout_manager.display_time(self.display_surface)
        self._draw_gold_pickup_popup()
        rts_active = (
            getattr(self, "rts_session", None) is not None
            and self.rts_session.is_active()
        )
        if not self.inventory_open:
            draw_belt_hud(self.display_surface, self.player, self.player.inventory)
            if rts_active:
                self.rts_session.draw()
            else:
                self._draw_interact_prompt()
        self.player_dead = getattr(self.player, "is_dead", False)
    
        # Grass  !

        ## Apply current wind force every certain time

        # if self.wind_timer >= self.wind_interval:
        #     wind_force = self.weather.calculate_wind_force()
        #     for row_index, row in enumerate(self.layout_manager.grass_tile_grid):
        #         for col_index, val in enumerate(row):
        #             if val:
        #                 tile_position = (col_index, row_index)
        #                 self.layout_manager.grass_manager.apply_force(tile_position, wind_force[0], wind_force[1])
        #     self.wind_timer = 0  # Reset the timer after applying force

        # # Finally, render the grass tiles
        # for row_index, row in enumerate(self.layout_manager.grass_tile_grid):
        #     for col_index, val in enumerate(row):
        #         if val:
        #             self.layout_manager.grass_manager.update_render(self.display_surface, dt)
    
 
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

class YSortCameraGroup(pygame.sprite.Group):
    def __init__(self, ground_sprites, grass_manager,overhead_areas):
        super().__init__()
        self.display_surface = pygame.display.get_surface()
        self.window_width, self.window_height = self.display_surface.get_size()
        self.half_width = self.display_surface.get_size()[0] // 2
        self.half_height = self.display_surface.get_size()[1] // 2

        self._apply_grass_viewport()
        
        self.offset = pygame.math.Vector2()
        self.grass_offset = pygame.math.Vector2()
        self.ground_sprites = ground_sprites
        self.ground_surface = None
        self.create_ground_surface()
        self.grass_manager = grass_manager
        self.update_grass_with_wind_frequency = 5000
        self.wind_last_affected_grass = 0
        self.t=0 # forgrass rotaryfunctin, name it better.
        self.last_player_grass_force_center = None
        self.grass_force_threshold_sq = 16  # 4px movement threshold before re-applying player force
        
        # Threading.
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.lock = Lock()
        
        self.overhead_areas = overhead_areas

    def _apply_grass_viewport(self):
        W, H = self.display_surface.get_size()
        p = GRASS_VIEWPORT_PERCENT / 100.0
        gw = max(1, int(W * p))
        gh = max(1, int(H * p))
        x = (W - gw) // 2
        y = (H - gh) // 2
        clip_rect = pygame.Rect(x, y, gw, gh).clip(pygame.Rect(0, 0, W, H))
        self.grass_surface = self.display_surface.subsurface(clip_rect)
        self.grass_half_width = self.grass_surface.get_width() // 2
        self.grass_half_height = self.grass_surface.get_height() // 2

    #@profile
    def update_parallel_inview(self, dt=None, weather=None, wind_force=(0, 0), num_threads=8, *args, **kwargs):
        #print("attempted parallel update")
        sprites_in_view = self.get_sprites_in_view()
        sprite_batches = [sprites_in_view[i::num_threads] for i in range(num_threads)]
        futures = []

        for batch in sprite_batches:
            future = self.executor.submit(self.update_for_parallel, batch, dt, self.lock)
            futures.append(future)

        updated_sprites = []
        for future in futures:
            updated_sprites.extend(future.result())

        # Extend with non-visible sprites
        updated_sprites.extend(sprite for sprite in self.sprites() if sprite not in updated_sprites)

        # Update self.sprites with the updated sprites
        self.sprites().clear()
        self.sprites().extend(updated_sprites)
        

    #@profile
    def update_parallel(self, obstruction_quad_tree,entity_quad_tree, dt=None, weather=None, wind_force=(0, 0), num_threads=1, *args, **kwargs):
        if num_threads <= 1:
            updated_sprites = self._update_batch(
                obstruction_quad_tree,
                entity_quad_tree,
                self.sprites(),
                dt=dt,
                lock=None,
                weather=weather,
            )
        else:
            sprite_batches = [self.sprites()[i::num_threads] for i in range(num_threads)]
            futures = []

            for batch in sprite_batches:
                future = self.executor.submit(self.update_for_parallel,
                                            obstruction_quad_tree,
                                            entity_quad_tree,
                                            batch,
                                            dt,
                                            self.lock,
                                            weather,  # Pass down the weather information
                                            wind_force,)
                futures.append(future)

            updated_sprites = []
            for future in futures:
                updated_sprites.extend(future.result())

        # Extend with non-visible sprites
        #updated_sprites.extend(sprite for sprite in self.sprites() if sprite not in updated_sprites)

        # Update self.sprites with the updated sprites
        self.sprites().clear()
        self.sprites().extend(updated_sprites)

    def set_grass_render_window_size_with_timeofday(self, light_level):
        # Single percent-based viewport for all light levels (see GRASS_VIEWPORT_PERCENT).
        self._apply_grass_viewport()

    def set_grass_grid(self,grass_grid):
        self.grass_grid = grass_grid

    def update_tile_on_ground_surface(self, tile):
        if not self.ground_surface:
            self.create_ground_surface()
        else:
            # Redraw only the area of the changed tile
            self.ground_surface.blit(tile.image, tile.rect.move(-self.min_x, -self.min_y))

    def create_ground_surface(self):
        if not self.ground_sprites:
            return
        self.min_x = min(sprite.rect.left for sprite in self.ground_sprites)
        self.max_x = max(sprite.rect.right for sprite in self.ground_sprites)
        self.min_y = min(sprite.rect.top for sprite in self.ground_sprites)
        self.max_y = max(sprite.rect.bottom for sprite in self.ground_sprites)

        width = self.max_x - self.min_x
        height = self.max_y - self.min_y

        self.ground_surface = pygame.Surface((width, height)).convert_alpha()
        self.ground_surface.fill((0, 0, 0, 0))
        for sprite in self.ground_sprites:
            self.ground_surface.blit(sprite.image, sprite.rect.move(-self.min_x, -self.min_y))
    #@profile
    def custom_draw(self, player,dt, wind_intensity, light_intensity):
        
        if self.ground_surface is None:
            self.create_ground_surface()

        W, H = self.display_surface.get_size()
        self.window_width, self.window_height = W, H
        self.half_width = W // 2
        self.half_height = H // 2

        self.set_grass_render_window_size_with_timeofday(light_intensity)

        self.offset.x = player.rect.centerx - self.half_width 
        self.offset.y = player.rect.centery - self.half_height
        self.grass_offset.x = player.rect.centerx - self.grass_half_width 
        self.grass_offset.y = player.rect.centery - self.grass_half_height
        
        
        ground_rect = self.ground_surface.get_rect(topleft=(-self.offset.x, -self.offset.y))
        self.display_surface.blit(self.ground_surface, ground_rect.topleft)
            
        # Shared wind mode keeps one base sway angle for visible grass; legacy mode
        # preserves the current position-dependent wave across the field.
        self.t += dt*1500*wind_intensity
        if GRASS_WIND_MODE == "shared_patch":
            shared_angle = int(math.sin(self.t / 60) * 15)
            rot_function = lambda x, y, angle=shared_angle: angle
        else:
            rot_function = lambda x, y: int(math.sin(self.t / 60 + x / 100) * 15)
        
        # if player on grass
        
        player_center = player.rect.center
        if self.last_player_grass_force_center is None:
            self.grass_manager.apply_force(player_center, 25, 20)
            self.last_player_grass_force_center = player_center
        else:
            dx = player_center[0] - self.last_player_grass_force_center[0]
            dy = player_center[1] - self.last_player_grass_force_center[1]
            if (dx * dx + dy * dy) >= self.grass_force_threshold_sq:
                self.grass_manager.apply_force(player_center, 25, 20)
                self.last_player_grass_force_center = player_center
        
        
        #print( self.grass_offset )
        #print( self.offset )
        
        # Draw grass relative to player
        self.grass_manager.update_render(self.grass_surface,
                                         dt, 
                                         offset=(self.grass_offset.x , 
                                                 self.grass_offset.y ),
                                      rot_function=rot_function )
        player_drawn = False
        for sprite in sorted(self.sprites(), key=lambda sprite: sprite.rect.centery):
            #print(sprite)
            #print(dir(sprite))
            offset_pos = sprite.rect.topleft - self.offset
            self.display_surface.blit(sprite.image, offset_pos)
            if hasattr(sprite, "monster_name"):
                if sprite.monster_name == 'raccoon':
                    self.grass_manager.apply_force( sprite.rect.center , 110 , 40)
                    
            # if hasattr(sprite, "type") and sprite.type == "player":
            #     player_drawn = True
            #     # Draw overhead areas if the player is within one
        # Draw overhead areas if the player is within one
        #if player_drawn:
        #print("overhead")
        #print(self.overhead_areas)
        for area, image_section in self.overhead_areas:
            #print(f"area : {area}")
            #print(f"player pos : {player.rect.center}")
            if area.colliderect(player.rect):
                self.display_surface.blit(image_section, (area.x - self.offset.x, area.y - self.offset.y))

    

    #@profile
    
    def set_overhead_areas(self, overhead_areas):
        self.overhead_areas = overhead_areas
    
    def update(self, dt=None, weather=None, wind_force=(0, 0), *args, **kwargs):
        
        for sprite in self.sprites():
            if isinstance(sprite, AnimatedEnvironmentSprite):
                sprite.update(weather, self.display_surface)
            else:
                sprite.update(dt)
    def _update_single_sprite(
        self,
        sprite,
        obstacle_quad_tree,
        entity_quad_tree,
        dt=None,
        weather=None,
    ):
        if isinstance(sprite, AnimatedEnvironmentSprite):  # keep legacy torch/weather behavior
            if isinstance(sprite, Torch):
                sprite.update(weather)
            else:
                sprite.update(weather)
        elif isinstance(sprite, Entity):
            sprite.update(
                dt=dt,
                QuadTree=obstacle_quad_tree,
                entity_quad_tree=entity_quad_tree,
            )
        else:
            sprite.update(dt=dt)

    def _update_batch(
        self,
        obstacle_quad_tree,
        entity_quad_tree,
        batch,
        dt=None,
        lock=None,
        weather=None,
    ):
        updated_sprites = []
        for sprite in batch:
            self._update_single_sprite(
                sprite,
                obstacle_quad_tree,
                entity_quad_tree,
                dt=dt,
                weather=weather,
            )
            if lock is None:
                updated_sprites.append(sprite)
            else:
                with lock:
                    updated_sprites.append(sprite)
        return updated_sprites

    #@profile
    def update_for_parallel(self,obstacle_quad_tree, entity_quad_tree, batch, dt=None,lock=None, weather=None, wind_force=(0, 0) , *args, **kwargs):
        return self._update_batch(
            obstacle_quad_tree,
            entity_quad_tree,
            batch,
            dt=dt,
            lock=lock,
            weather=weather,
        )
                    
    def is_tile_in_view(self, tile_position):
        """
        Check if a tile at the given position is within the visible area.
        
        Args:
            tile_position (tuple): Position of the tile (x, y).
    
        Returns:
            bool: True if the tile is within the visible area, False otherwise.
        """
        tile_x, tile_y = tile_position
        tile_size = TILESIZE  # Adjust this based on your tile size
        screen_width, screen_height = self.display_surface.get_size()
        screen_left = self.offset.x
        screen_right = self.offset.x + screen_width
        screen_top = self.offset.y
        screen_bottom = self.offset.y + screen_height
        
        # Calculate the bounding box of the tile
        tile_left = tile_x
        tile_right = tile_x + tile_size
        tile_top = tile_y
        tile_bottom = tile_y + tile_size
        
        # Check if any part of the tile is within the visible area
        return (tile_left < screen_right and tile_right > screen_left and
                tile_top < screen_bottom and tile_bottom > screen_top)

    def get_sprites_in_view(self):
        # Determine the visible area based on the player's position and the game window size
        visible_rect = pygame.Rect(self.offset.x, self.offset.y, self.window_width, self.window_height)
        
        # Filter out sprites that are outside the visible area
        visible_sprites = [sprite for sprite in self.sprites() if visible_rect.colliderect(sprite.rect)]
        
        return visible_sprites
                
                
        #### I need to not iterate over the entire grid for this maybe ? still its taking 95% in 
        # the grass method so ... i guess not.
                
        
        
        
        
        ## Ideas to test : have constant force applied to single place to check what it does
        #                  only apply forced to tiles in view.
        
        
    # Pass wind force to the grass manager
 
             

class YSortCameraGroup_old(pygame.sprite.Group):
    def __init__(self,ground_sprites): # Ground sprites in this version because it defines the ground with tiles ( ground_sprites ) 
        super().__init__()
        self.display_surface = pygame.display.get_surface()
        self.half_width = self.display_surface.get_size()[0] // 2
        self.half_height = self.display_surface.get_size()[1] // 2
        self.offset = pygame.math.Vector2()
        self.ground_sprites = ground_sprites

#        self.floor_surf = pygame.image.load("../Graphics/Tilemap/Ground.png").convert()
#        self.floor_rect = self.floor_surf.get_rect(topleft = (0, 0))
    ###@profile #decorator to be used for profiling with line_profile, must run Main like this : kernprof -l -v Main2.py
    def custom_draw_withearthquakeeffect(self, player):
        
        self.offset.x = player.rect.centerx - self.half_width
        self.offset.y = player.rect.centery - self.half_height

        # Draw ground tiles with slight offset and blending
        for sprite in sorted(self.ground_sprites, key=lambda sprite: sprite.rect.centery):
            offset_pos = sprite.rect.topleft - self.offset
            # Slightly offset tile position
            offset_pos += pygame.math.Vector2(random.uniform(-1, 1), random.uniform(-1, 1))
            # Draw tile
            self.display_surface.blit(sprite.image, offset_pos)
            # Draw semi-transparent overlay on tile edges for blending
            overlay = pygame.Surface((sprite.rect.width, sprite.rect.height), pygame.SRCALPHA)
            pygame.draw.rect(overlay, (255, 255, 255, 128), overlay.get_rect(), 1)
            self.display_surface.blit(overlay, offset_pos)

        # Draw other sprites
        for sprite in sorted(self.sprites(), key=lambda sprite: sprite.rect.centery):
            offset_pos = sprite.rect.topleft - self.offset
            self.display_surface.blit(sprite.image, offset_pos)



    def custom_draw(self, player):
        self.offset.x = player.rect.centerx - self.half_width
        self.offset.y = player.rect.centery - self.half_height

  # Draw ground tiles first
        for sprite in sorted(self.ground_sprites, key=lambda sprite: sprite.rect.centery):
            offset_pos = sprite.rect.topleft - self.offset
            self.display_surface.blit(sprite.image, offset_pos)

        for sprite in sorted(self.sprites(), key=lambda sprite: sprite.rect.centery):
            offset_pos = sprite.rect.topleft - self.offset
            self.display_surface.blit(sprite.image, offset_pos)



    def update(self,dt = None, *args, **kwargs):
        # Update all sprites, passing the player as an argument to those that need it
        for sprite in self.sprites():

            # JUST A POTENTIAL EFFICIENCY IMPROVEMENT TO ONLY PASS PLAYER TO NECESSARY UPDATES ? NO, ITS JUST IF I MAKE THE ENEMY_UPDATE AND REGULAR SPRITE.update method the  same...
            # Pretty sure it was jst a bad idea, but there it is.

            #if hasattr(sprite, 'update_with_player') and sprite.update_with_players:
                #sprite.update(self, player)  # Custom method for sprites needing the player
            #else:
            if isinstance(sprite, Eskimo):
                #print(f"SPRITE BEFORE UPDATE : {sprite}")
                sprite.update(dt)
                #print(f"SPRITE AFTER UPDATE : {sprite}")
            else:
                sprite.update(*args, **kwargs)

