#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Feb  8 01:03:00 2025

@author: fresh
"""




### WL 

# Need to change level to import this new layout manager
# Need level select to only  have new .tmx levels
# then i think i can do basic object and ground level

#### Then need to do triggers and spawners in tmx file , use grassmanager etc.

import pygame
from Settings import *
from Tile import Tile
from DaytimeBrightnessOverlay import DaytimeBrightnessOverlay
import pytmx
from YsortCameraGroup import YSortCameraGroup
from pytmx.util_pygame import load_pygame
from GrassManager import GrassManager
from QuadTree import QuadTree
from QuadTree import QuadTreeManager
from hashRect import HashableRect
from EffectArea import EffectArea
from Torch import Torch
from Tree import Tree
from AnimationSprite import AnimationSprite
import json
import logging
import math
import os
import random

from game_logging import get_tmx_effect_placement_logger, get_tmx_layout_logger
from benchmark_runtime import BENCHMARK_RUNTIME
from benchmark_broadphase import MovingEntityBroadphaseAdapter
from Entity import Entity
from ItemVisual import ItemVisual

_tmx_layout_log = get_tmx_layout_logger()

# TMX tile object: custom property env_anim_type = "tree" | "torch" (case-insensitive).
# Keyword maps 1:1 to sprite_animation_config (legacy Map7 tree1/torch1 paths).
ENV_ANIM_REGISTRY = {
    "torch": Torch,
    "tree": Tree,
}

ENV_ANIM_SPRITE_CONFIG_BY_TYPE = {
    "tree": {
        "normal": "../levels/Map7/start/Objects/object_images/tree1/normal",
        "strong_wind_left": "../levels/Map7/start/Objects/object_images/tree1/strong_wind_left",
        "strong_wind_right": "../levels/Map7/start/Objects/object_images/tree1/strong_wind_right",
    },
    "torch": {
        "normal": "../levels/Map7/start/Objects/object_images/torch1/normal",
    },
}


class LayoutManager:
    
    def __init__(self, 
                 selected_player_info_dir,
                 TILESIZE,
                 restore_persistent_enemies_callback=None,
                 initialize_map_items_callback=None,
                 benchmark_runtime=None,
                 ):
        # This class manages layouts of a level with triggers and logs
        self.start_map_layout(selected_player_info_dir = selected_player_info_dir,
                        TILESIZE = TILESIZE,
                        restore_persistent_enemies_callback=restore_persistent_enemies_callback,
                        initialize_map_items_callback=initialize_map_items_callback)
        self.benchmark_runtime = benchmark_runtime or BENCHMARK_RUNTIME

    def start_map_layout(self,
                         selected_player_info_dir,
                         TILESIZE,
                         restore_persistent_enemies_callback=None,
                         initialize_map_items_callback=None,
                         Player = None, 
                         daytime_layout = True,
                         prepared_daytimeoverlay = None):# this last param sucks, showing how bad my map change logic is.
        # This function initializes the LayoutManager instance
        self.TILESIZE = TILESIZE
        self.csv_layout_width = 40* TILESIZE # TODO hard coded atm, i am not sure exactly how to configure this config ( i am initializing the QuadTree before accessing layout csvs thats the only issue, initialize it after and keep that info)
        self.csv_layout_height = 40* TILESIZE

 


        #print(f"self.obstacle_quad_tree : {self.obstacle_quad_tree.cx}")
        self.selected_player_info_dir = selected_player_info_dir
        self.restore_persistent_enemies_callback = restore_persistent_enemies_callback
    
        # Initialize grass manager
        self.grass_manager = GrassManager(
            grass_path="../Graphics/Grass",
            tile_size=TILESIZE,
            stiffness=600,
            max_unique=3,
            place_range=[0, 1],
            rotation_bucket_degrees=GRASS_ROTATION_BUCKET_DEGREES,
        )
        self._grass_profiles = {}
    
        # Initialize sprite groups
        self.ground_sprites = pygame.sprite.Group()
        self.obstacle_sprites = pygame.sprite.Group()
        self.trigger_sprites = pygame.sprite.Group()
        self.overhead_areas = []
    
        # Initialize camera group for sorting sprites
        self.visible_sprites = YSortCameraGroup(self.ground_sprites, self.grass_manager, self.overhead_areas)
    
       # Positioning here again, its a bit of a mess , i think i do this in start map of level first and it gets reset here unwillingly so i set it again
       
        self.daytime_layout = daytime_layout
        # Set animation flag
        self.animation_active = False
    
    
        # Setup timer
        
        self.start_ticks = pygame.time.get_ticks()
        

    
        # Initialize player and callback
        self.player = Player
        
        self.initialize_map_items_callback = initialize_map_items_callback
        self.item_spawner = None
    
        # Initialize tile map and daytime brightness overlay
        self.tile_map = {}
        
        #print(f"daytime layout : {daytime_layout}")
        #print(type(daytime_layout))
        if self.daytime_layout:
            if prepared_daytimeoverlay:
                self.daytime_brightness_overlay = prepared_daytimeoverlay
            else: 
                self.daytime_brightness_overlay = DaytimeBrightnessOverlay()
        else: self.daytime_brightness_overlay = None
    
    
    
    
    def display_time( self, display_surface):
        # Calculate elapsed time in milliseconds
        elapsed_ticks = pygame.time.get_ticks() - self.start_ticks
        elapsed_seconds = elapsed_ticks // 1000
        minutes = elapsed_seconds // 60
        seconds = elapsed_seconds % 60
    
        # Format time as MM:SS
        time_string = f"{minutes:02}:{seconds:02}"
        
        # Render time string
        text_surface = pygame.font.Font(None, 36).render(time_string, True, (255, 255, 255))
        
        # Position the text at the top-left corner
        
        display_surface.blit(text_surface, (display_surface.get_size()[0]/2, 10))
    
    
    def add_obstacle_sprite_to_quad_tree(self, obstacle_sprite, alive=True, remove_existing = True):
        
        
        ## This is a mess im controlling things here and then also in the quadtree methods
        #  Needs cleanup
        #print(type(obstacle_sprite))
        #print(isinstance(obstacle_sprite,Entity))
        #if  remove_existing:
        #    print(" is netity and remove existing and passed condition ")
        #    self.entity_quad_tree.manager.remove( obstacle_sprite._id, remove_existing )
        #if alive:
        #print(f"alive : {alive}")
        # Add the obstacle sprite to the quadtree
        self.entity_quad_tree.insert(
            obstacle_sprite,
            alive=alive,
            remove_existing=remove_existing,
        )
        
            # The above is quite confusing, the insert method actually doesnt insert if alive is false,
            # the insert method deletes every time, if remove_existing is true
            

    def remove_obstacle_sprite_from_quad_tree(self, obstacle_sprite):# not used at the moment
        # Remove the obstacle sprite from the quadtree
        self.obstacle_quad_tree.delete(obstacle_sprite)

    def set_player(self, player):
        """Sets the player object for layout interaction."""
        self.player = player

    def trigger_animation(self, frames, position, speed):
        AnimationSprite(frames, position, speed, [self.visible_sprites])

    def set_spawner(self, spawner, layout_callback_update_quad_tree):
        """Sets the Spawner object for enemy management."""
        self.spawner = spawner  
        self.spawner.set_layout_callback_update_quad_tree( layout_callback_update_quad_tree )

    def set_item_spawner(self, item_spawner):
        """ItemSpawner for TMX item layers and pickups (optional)."""
        self.item_spawner = item_spawner

    def add_item_visual(self, item):
        """Wrap Item in ItemVisual and add to visible_sprites."""
        item_visual = ItemVisual(item=item, groups=[self.visible_sprites])
        self.visible_sprites.add(item_visual)

    def _load_grass_profiles(self, tmx_path):
        """Load grass_profiles.json from layout folder first, else shared levels/tmx/."""
        self._grass_profiles = {}
        candidates = []
        if tmx_path:
            candidates.append(
                os.path.normpath(os.path.join(os.path.abspath(tmx_path), "grass_profiles.json"))
            )
        _code_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(
            os.path.normpath(os.path.join(_code_dir, "..", "levels", "tmx", "grass_profiles.json"))
        )
        for path in candidates:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self._grass_profiles = data
                    else:
                        _tmx_layout_log.debug(
                            "grass_profiles.json must be a JSON object, got %s: %s",
                            type(data).__name__,
                            path,
                        )
                    return
                except (json.JSONDecodeError, OSError) as e:
                    _tmx_layout_log.debug("Failed to load grass profiles from %s: %s", path, e)
                    return
        _tmx_layout_log.debug(
            "No grass_profiles.json found; grass_profile on tiles will be ignored."
        )

    def _resolve_grass_profile(self, name):
        """
        Return a normalized placement profile for GrassManager.place_tile, or None on error.
        """
        if name is None:
            return None
        key = str(name).strip()
        if not key:
            return None
        prof = self._grass_profiles.get(key)
        if not prof:
            _tmx_layout_log.debug(
                "Unknown grass_profile=%r; add it to grass_profiles.json", key
            )
            return None
        options = prof.get("grass_options")
        if not isinstance(options, list) or len(options) == 0:
            _tmx_layout_log.debug(
                "grass_profile=%r needs non-empty grass_options list", key
            )
            return None
        try:
            options = [int(x) for x in options]
        except (TypeError, ValueError):
            _tmx_layout_log.debug("grass_profile=%r grass_options must be integers", key)
            return None
        if "density" in prof:
            try:
                density = max(1, int(prof["density"]))
            except (TypeError, ValueError):
                _tmx_layout_log.debug("grass_profile=%r has invalid density", key)
                return None
        else:
            try:
                mean = float(prof.get("density_mean", 40))
                sigma = float(prof.get("density_sigma", 0))
            except (TypeError, ValueError):
                _tmx_layout_log.debug(
                    "grass_profile=%r has invalid density_mean/density_sigma", key
                )
                return None
            if sigma > 0:
                density = max(1, round(random.gauss(mean, sigma)))
            else:
                density = max(1, int(mean))
        try:
            wind_scale = float(prof.get("wind_scale", 1.0))
            force_scale = float(prof.get("force_scale", 1.0))
            stiffness = float(prof.get("stiffness", self.grass_manager.stiffness))
            z_index = int(prof.get("z_index", 0))
        except (TypeError, ValueError):
            _tmx_layout_log.debug(
                "grass_profile=%r has invalid wind_scale/force_scale/stiffness/z_index",
                key,
            )
            return None
        return {
            "profile_key": key,
            "density": density,
            "grass_options": list(options),
            "wind_scale": wind_scale,
            "force_scale": force_scale,
            "stiffness": stiffness,
            "z_index": z_index,
        }


## Create ground sprites:

#self.tmx_ground_layers = [  x  for x in  self.tmxdata.layers if x.name.find("Tile")!=1 ]
    
    def create_ground_layer( self,tmx_ground_layer ):
            
        layer_number_posstart = str(tmx_ground_layer).find("[")
        layer_number_posend = str(tmx_ground_layer).find("]")  ## This is defo not ideal, its how i get layer pos atm
                                                                # no clearbetter way to do it , i could manage the ids of layers..
        layer_number = str(tmx_ground_layer)[layer_number_posstart+1:layer_number_posend]   
        layer_number = int(layer_number)-1
        layer_name_lower = getattr(tmx_ground_layer, "name", "").lower()
        layer_has_grass = "grass" in layer_name_lower

        for tile in tmx_ground_layer.tiles():
            tile_properties = {}
            try:
                raw_props = self.tmxdata.get_tile_properties(tile[0], tile[1], layer_number)
                tile_properties = dict(raw_props) if raw_props else {}
                valid_interaction_types = [tile_properties.get("valid_interaction_types")]
            except Exception:
                valid_interaction_types = []
            gid = self.tmxdata.get_tile_gid(tile[0], tile[1], layer_number)
            #print(f"tile:{tile}")
            #print(gid)

            surface = self.tmxdata.get_tile_image(tile[0], tile[1], layer_number)
            if not surface:
                continue
            surface = surface.copy()

            width, height = surface.get_size()  # Get original size
            #print(f"Original Size: {width}x{height}")  # Debugging

            surface = pygame.transform.scale(surface, (TILESIZE, TILESIZE))

            new_tile = Tile(pos = (tile[0]*TILESIZE,tile[1]*TILESIZE),# could refactor pos its used atleast twice here
                            groups = [self.ground_sprites],
                            sprite_type ='ground',
                            surface = surface, # only surface if imported with pygame func
                            valid_interaction_types = valid_interaction_types)

            self.tile_map[(tile[0], tile[1])] = new_tile

            if layer_has_grass:
                gp = tile_properties.get("grass_profile")
                if gp is not None and str(gp).strip():
                    resolved = self._resolve_grass_profile(gp)
                    if resolved:
                        tx, ty = tile[0], tile[1]
                        self.grass_manager.place_tile(
                            location=(tx, ty), density=resolved
                        )
                        grid = getattr(self, "grass_tile_grid", None)
                        if grid is not None and 0 <= ty < len(grid) and 0 <= tx < len(grid[0]):
                            grid[ty][tx] = True

        
    def _game_rect_for_tmx_object(self, object_, tiled_tile_width, tiled_tile_height):
        """Tiled object position/size to game-space pixel rect (x, y, w, h)."""
        x_pos = (object_.x * TILESIZE) / tiled_tile_width
        y_pos = (object_.y * TILESIZE) / tiled_tile_height
        width_scaling_factor = TILESIZE / tiled_tile_width
        height_scaling_factor = TILESIZE / tiled_tile_height
        gw = object_.width * width_scaling_factor
        gh = object_.height * height_scaling_factor
        if gw <= 0 or gh <= 0:
            gw = TILESIZE
            gh = TILESIZE
        return x_pos, y_pos, gw, gh

    def _place_grass_cells_in_rect(self, x_pos, y_pos, gw, gh, grass_profile):
        """Fill all tile cells overlapping the axis-aligned rect with a grass placement profile."""
        tx0 = int(math.floor(x_pos / TILESIZE))
        ty0 = int(math.floor(y_pos / TILESIZE))
        tx1 = int(math.floor((x_pos + gw - 1) / TILESIZE))
        ty1 = int(math.floor((y_pos + gh - 1) / TILESIZE))
        grid = getattr(self, "grass_tile_grid", None)
        if grid is not None:
            gh_rows = len(grid)
            gw_cols = len(grid[0])
            ty_lo = max(0, ty0)
            ty_hi = min(ty1, gh_rows - 1)
            tx_lo = max(0, tx0)
            tx_hi = min(tx1, gw_cols - 1)
        else:
            ty_lo, ty_hi = ty0, ty1
            tx_lo, tx_hi = tx0, tx1
        for ty in range(ty_lo, ty_hi + 1):
            for tx in range(tx_lo, tx_hi + 1):
                self.grass_manager.place_tile(
                    location=(tx, ty), density=grass_profile
                )
                if grid is not None and 0 <= ty < len(grid) and 0 <= tx < len(grid[0]):
                    grid[ty][tx] = True

    def create_grass_object_layer(self, tmx_object_layer):
        """
        Object layer whose name contains 'grass': each object needs grass_profile on the object.
        Fills all tile cells overlapping the object's axis-aligned bbox (no Tile sprites).
        """
        layer_name = getattr(tmx_object_layer, "name", "")
        tiled_tile_width = self.tmxdata.tilewidth
        tiled_tile_height = self.tmxdata.tileheight

        for object_ in tmx_object_layer:
            raw_props = getattr(object_, "properties", None) or {}
            props = dict(raw_props) if raw_props is not None else {}
            gp = props.get("grass_profile")
            if gp is None or not str(gp).strip():
                _tmx_layout_log.debug(
                    "Grass layer %r object missing grass_profile; skipping object",
                    layer_name,
                )
                continue
            resolved = self._resolve_grass_profile(gp)
            if not resolved:
                continue
            x_pos, y_pos, gw, gh = self._game_rect_for_tmx_object(
                object_, tiled_tile_width, tiled_tile_height
            )
            self._place_grass_cells_in_rect(x_pos, y_pos, gw, gh, resolved)

    def _try_spawn_animated_env_object(self, object_, props, x_pos, y_pos, width_scaling_factor, height_scaling_factor):
        """
        If env_anim_type is tree or torch, spawn using ENV_ANIM_SPRITE_CONFIG_BY_TYPE.
        On failure, log a warning and return False (caller may fall back to static tile).
        """
        env_type = props.get("env_anim_type")
        if env_type is None or (isinstance(env_type, str) and not env_type.strip()):
            return False
        key = str(env_type).strip().lower()
        cls = ENV_ANIM_REGISTRY.get(key)
        if cls is None:
            _tmx_layout_log.debug(
                "Unknown env_anim_type=%r; expected one of %s",
                env_type,
                list(ENV_ANIM_REGISTRY),
            )
            return False
        config = ENV_ANIM_SPRITE_CONFIG_BY_TYPE.get(key)
        if not config:
            _tmx_layout_log.debug(
                "No sprite config wired for env_anim_type=%r.", key
            )
            return False
        try:
            cls((x_pos, y_pos), [self.visible_sprites, self.obstacle_sprites], config)
            return True
        except Exception as e:
            _tmx_layout_log.debug(
                "Failed to spawn %s at (%s, %s): %s",
                cls.__name__,
                x_pos,
                y_pos,
                e,
            )
            return False

    def create_object_layer( self,tmx_object_layer ):
        
        ## Fix discrepancy between tiled map tilesize and game tilesize
        
        tiled_tile_width = self.tmxdata.tilewidth
        tiled_tile_height = self.tmxdata.tileheight
        
        for object_ in tmx_object_layer:
        
            x_pos = (object_.x*TILESIZE ) / tiled_tile_width
            y_pos = (object_.y*TILESIZE ) / tiled_tile_height
            width_scaling_factor = TILESIZE/tiled_tile_width
            height_scaling_factor = TILESIZE/tiled_tile_height

            raw_props = getattr(object_, "properties", None) or {}
            props = dict(raw_props) if raw_props is not None else {}

            if self._try_spawn_animated_env_object(
                object_, props, x_pos, y_pos, width_scaling_factor, height_scaling_factor
            ):
                continue

            image = object_.image

            
            if image is not None:
                # SCALE
                image = pygame.transform.scale( image, (object_.width*width_scaling_factor, object_.height*height_scaling_factor ) )
                mask = pygame.mask.from_surface(image)
            else:
                # Non-image objects (shapes) should be handled as effect layers, skip drawing
                continue
            
            new_tile = Tile((x_pos, y_pos),
                            [self.obstacle_sprites,self.ground_sprites], 
                            'ground',
                            mask = mask,
                            surface = image)
    
    
    
    
    def _make_effect_area_from_tiled_object(self, obj, layer_name, idx):
        """
        Convert a pytmx shape (rect/ellipse/polygon) into an EffectArea.
        This:
          • computes the game-space rect
          • draws the shape ONLY to generate a mask
          • stores rect + mask + properties + original tmx object
        """
    
        # --- Tiled → Game space scaling ---
        tw = self.tmxdata.tilewidth
        th = self.tmxdata.tileheight
        sx = self.TILESIZE / tw
        sy = self.TILESIZE / th
    
        x_game = obj.x * sx
        y_game = obj.y * sy
        w_game = obj.width * sx
        h_game = obj.height * sy
    
        surf_w = max(1, int(round(w_game)))
        surf_h = max(1, int(round(h_game)))
    
        # Local surface just for mask creation
        surf = pygame.Surface((surf_w, surf_h), pygame.SRCALPHA)
    
        # --- Determine shape + draw to local surface ---
        if getattr(obj, "points", None):  # polygon
            pts = [(int(px * sx), int(py * sy)) for px, py in obj.points]
            pygame.draw.polygon(surf, (255, 255, 255, 255), pts)
        elif getattr(obj, "ellipse", False):  # ellipse
            pygame.draw.ellipse(surf, (255, 255, 255, 255), (0, 0, surf_w, surf_h))
        else:  # rectangle fallback
            pygame.draw.rect(surf, (255, 255, 255, 255), (0, 0, surf_w, surf_h))
    
        # --- Create mask ---
        mask = pygame.mask.from_surface(surf)
        
        # --- Rect in game coords ---
        # Your engine uses Tiled Y as top-left, so no subtract of height.
        rect = pygame.Rect(int(x_game), int(y_game), surf_w, surf_h)
    
        _fx_log = get_tmx_effect_placement_logger()
        if _fx_log.isEnabledFor(logging.DEBUG):
            mask_pixel_count = mask.count() if mask else 0
            expected_ellipse_area = (
                math.pi * (surf_w / 2) * (surf_h / 2)
                if getattr(obj, "ellipse", False)
                else surf_w * surf_h
            )
            _fx_log.debug(
                "Effect %s_%s:\n"
                "  TMX raw: obj.x=%s, obj.y=%s, obj.width=%s, obj.height=%s\n"
                "  Scaling: sx=%s, sy=%s, TILESIZE=%s, tilewidth=%s, tileheight=%s\n"
                "  Calculated: x_game=%s, y_game=%s, w_game=%s, h_game=%s\n"
                "  Final rect: %s (surf_w=%s, surf_h=%s)\n"
                "  Mask pixel count: %s, Expected ellipse area: %.1f\n"
                "  Mask size: %s",
                layer_name,
                idx,
                obj.x,
                obj.y,
                obj.width,
                obj.height,
                sx,
                sy,
                self.TILESIZE,
                tw,
                th,
                x_game,
                y_game,
                w_game,
                h_game,
                rect,
                surf_w,
                surf_h,
                mask_pixel_count,
                expected_ellipse_area,
                mask.get_size() if mask else "None",
            )
    
        # --- Properties ---
        props = dict(obj.properties) if hasattr(obj, "properties") else {}
    
        # --- Create final EffectArea ---
        area = EffectArea(
            rect=rect,
            mask=mask,
            properties=props,
            _id=f"effect_{layer_name}_{idx}",
            tmx_object=obj
        )

        return area

    
    
    
    def create_effect_layer(self, tmx_object_layer):
        _fx_layer_log = get_tmx_effect_placement_logger()
        _fx_layer_log.debug("creating effect layer")
        _fx_layer_log.debug("%s", tmx_object_layer)
        items = []
        layer_name = getattr(tmx_object_layer, "name", f"effect_layer_{len(getattr(self,'effect_quad_trees',{}))}")
        for idx, obj in enumerate(tmx_object_layer):
            area = self._make_effect_area_from_tiled_object(obj, layer_name, idx)
            items.append(area)
    
        manager = QuadTreeManager()
        tree = QuadTree(
            items=items,
            depth=8,
            bounding_rect=pygame.rect.Rect(0, 0, self.csv_layout_width, self.csv_layout_height),
            manager=manager
        )
    
        # ensure dicts exist (initialize in start_map_layout)
        if not hasattr(self, "effect_quad_trees"):
            self.effect_quad_trees = {}
            self.effect_quad_tree_managers = {}
            self.all_effect_areas = []  # Store all effect areas for debug visualization
    
        self.effect_quad_trees[layer_name] = tree
        self.effect_quad_tree_managers[layer_name] = manager
        self.all_effect_areas.extend(items)  # Add to debug list
        
        # Update debug visualization in visible_sprites
        if hasattr(self, 'visible_sprites'):
            self.visible_sprites.debug_effect_areas = self.all_effect_areas
        
        return tree

    def create_spawner_layer(self, tmx_object_layer):
        """
        Process spawner objects from a Tiled object layer.
        Extracts spawner config properties and creates spawn areas.
        """
        if not hasattr(self, 'spawner'):
            _tmx_layout_log.debug(
                "Warning: Spawner not set, cannot process spawner layer"
            )
            return
        
        layer_name = getattr(tmx_object_layer, "name", "spawner")
        
        # Get Tiled tile dimensions for coordinate conversion
        tiled_tile_width = self.tmxdata.tilewidth
        tiled_tile_height = self.tmxdata.tileheight
        
        for obj in tmx_object_layer:
            # Extract properties
            props = dict(obj.properties) if hasattr(obj, "properties") else {}
            
            # Extract spawner config properties
            spawner_config = self._extract_spawner_config(props)
            
            if not spawner_config:
                continue
            
            # Generate spawn_matrix from object dimensions
            spawn_matrix = self._generate_spawn_matrix(obj, tiled_tile_width, tiled_tile_height)
            
            # Convert coordinates and create object_info
            object_info = self._create_spawner_object_info(obj, tiled_tile_width, tiled_tile_height)
            
            # Add spawn area to spawner
            self.spawner.add_spawn_area(spawn_matrix, spawner_config, object_info)

    def create_item_object_layer(self, tmx_object_layer):
        """
        Object layer whose name contains 'item': each object needs item_id (standard_items.json).
        Position uses game-space topleft from _game_rect_for_tmx_object (pixels).
        """
        if not self.item_spawner:
            _tmx_layout_log.debug(
                "item_spawner not set; skipping item object layer %r",
                getattr(tmx_object_layer, "name", ""),
            )
            return
        tiled_tile_width = self.tmxdata.tilewidth
        tiled_tile_height = self.tmxdata.tileheight
        mapping = getattr(self.item_spawner, "item_mapping", None)
        if not mapping:
            _tmx_layout_log.debug("item_spawner has no item_mapping; load_item_mapping first")
            return

        for obj in tmx_object_layer:
            props = dict(obj.properties) if hasattr(obj, "properties") else {}
            item_id = props.get("item_id")
            if item_id is None or (isinstance(item_id, str) and not str(item_id).strip()):
                _tmx_layout_log.debug(
                    "Item layer object missing item_id; skipping in layer %r",
                    getattr(tmx_object_layer, "name", ""),
                )
                continue
            item_id = str(item_id).strip()
            cfg = mapping.get(item_id)
            if not cfg:
                _tmx_layout_log.debug("Unknown item_id %r in item layer", item_id)
                continue
            x_px, y_px, _gw, _gh = self._game_rect_for_tmx_object(
                obj, tiled_tile_width, tiled_tile_height
            )
            position = [float(x_px), float(y_px)]
            item = self.item_spawner.create_item(cfg, position)
            self.add_item_visual(item)

    def _extract_spawner_config(self, props):
        """
        Read a single Tiled property spawner_config: JSON string (or dict) with full spawner config.
        Same shape as legacy *.json spawner files. Returns None on missing/invalid input.
        """
        raw = props.get("spawner_config")
        if raw is None:
            _tmx_layout_log.debug(
                "Spawner object missing spawner_config property"
            )
            return None
        if isinstance(raw, str) and not str(raw).strip():
            _tmx_layout_log.debug("Spawner spawner_config is empty")
            return None

        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                _tmx_layout_log.debug("Invalid spawner_config JSON: %s", e)
                return None
        elif isinstance(raw, dict):
            data = dict(raw)
        else:
            _tmx_layout_log.debug(
                "spawner_config must be string or dict, got %s",
                type(raw).__name__,
            )
            return None

        if not isinstance(data, dict):
            _tmx_layout_log.debug(
                "spawner_config JSON must be an object at top level"
            )
            return None

        weights = data.get("enemy_spawn_weights")
        if weights is None:
            _tmx_layout_log.debug(
                "spawner_config must include enemy_spawn_weights"
            )
            return None
        if isinstance(weights, str):
            try:
                weights = json.loads(weights)
            except json.JSONDecodeError as e:
                _tmx_layout_log.debug(
                    "Could not parse enemy_spawn_weights as JSON: %s", e
                )
                return None
        if not isinstance(weights, dict):
            _tmx_layout_log.debug(
                "enemy_spawn_weights must be an object (dict)"
            )
            return None

        config = {
            "enemy_spawn_weights": weights,
            "spawn_type": data.get("spawn_type", "random_weights"),
            "frequency": data.get("frequency", 10000),
            "spawn_limit": data.get("spawn_limit", 60),
            "spawn_number": data.get("spawn_number", 1),
        }
        for opt in ("distance", "time_scaled", "scale_type", "scale_max"):
            if opt in data:
                config[opt] = data[opt]

        if "item_drop_info" in data:
            raw_drop = data["item_drop_info"]
            if isinstance(raw_drop, dict):
                config["item_drop_info"] = raw_drop
            else:
                _tmx_layout_log.debug(
                    "spawner_config item_drop_info must be an object, got %s",
                    type(raw_drop).__name__,
                )

        return config
    
    def _generate_spawn_matrix(self, obj, tiled_tile_width, tiled_tile_height):
        """
        Generate spawn_matrix from object dimensions.
        Returns 2D array filled with 1s (all tiles are valid spawn positions).
        """
        # Convert pixel dimensions to tile dimensions
        width_tiles = math.ceil(obj.width / tiled_tile_width)
        height_tiles = math.ceil(obj.height / tiled_tile_height)
        
        # Ensure at least 1x1
        width_tiles = max(1, width_tiles)
        height_tiles = max(1, height_tiles)
        
        # Create matrix filled with 1s (all tiles valid spawn positions)
        spawn_matrix = [[1 for _ in range(width_tiles)] for _ in range(height_tiles)]
        
        return spawn_matrix
    
    def _create_spawner_object_info(self, obj, tiled_tile_width, tiled_tile_height):
        """
        Spawner placement uses the same math as grass / objects (_game_rect_for_tmx_object).

        Stores the full game-space rect in pixels so Spawner can measure proximity as
        distance to the box (not only the top-left corner — important for large areas).
        """
        x_px, y_px, gw, gh = self._game_rect_for_tmx_object(
            obj, tiled_tile_width, tiled_tile_height
        )
        ts = float(self.TILESIZE)
        anchor_tx = float(x_px) / ts
        anchor_ty = float(y_px) / ts
        return {
            "anchor_tx": anchor_tx,
            "anchor_ty": anchor_ty,
            "x_pos": anchor_tx,
            "y_pos": anchor_ty,
            "rect_x_px": float(x_px),
            "rect_y_px": float(y_px),
            "rect_w_px": float(gw),
            "rect_h_px": float(gh),
        }

    
    


    def initialize_layout(self,
                          tmx_path, ## This is actually just the folder for now
                          player_position=None,
                          restart = False, 
                          Player = None,
                          daytime_layout=False, 
                          prepared_daytimeoverlay = None):
        
                

        
        if hasattr(self, 'spawner'):
            self.spawner.spawn_areas = [] # each layout start fresh spawn areas if any.ofc.
        #print(f"starting layout : {layout_path}")        
        # Clear existing sprites from groups
        self.ground_sprites.empty()
        self.visible_sprites.empty()
        self.trigger_sprites.empty()
        self.obstacle_sprites.empty()
        self.last_trigger_time = None

        self.effect_quad_trees = {}         
        self.effect_quad_tree_managers = {}
        self.all_effect_areas = []  # Store all effect areas for debug visualization 
        
        self.tmxdata = load_pygame( tmx_path + '/map.tmx' )

        # Fresh procedural grass for this map (LayoutManager reuses one GrassManager).
        self.grass_manager.grass_tiles.clear()
        self._load_grass_profiles(tmx_path)
        self.grass_tile_grid = [
            [None for _ in range(self.tmxdata.width)] for _ in range(self.tmxdata.height)
        ]
        
        self.tmx_ground_layers = [  x  for x in  self.tmxdata.layers if type(x).__name__.find("TileLayer") != -1 ]

        self.tmx_object_layers = [  x  for x in  self.tmxdata.layers if type(x).__name__.find("ObjectGroup") != -1 ]
        # NOTE : Becuase of how tiled tmx data structure works, an effect Layer is a Object Layer, so i just make sure name contains Effect
        #        and check within the ground layers loop which initialization method i should use



        ## I need to create the effect layers loops here.
        #  1. how do i identify them, it uses the name and find... its using the type actually, 
        #    -> Get the import going to check the name and usage.
                
            

        for layout in self.tmx_ground_layers:

            self.create_ground_layer(layout)

        self.visible_sprites.set_grass_grid(self.grass_tile_grid)

        for layout in self.tmx_object_layers:
            # Check if layer name contains "Effect" OR if any object has no image (shape-based effects)
            layer_name = getattr(layout, "name", "")
            layer_name_lower = layer_name.lower()
            has_effect_name = layer_name.find("Effect") != -1
            has_spawner_name = layer_name_lower.find("spawner") != -1
            has_item_name = "item" in layer_name_lower
            has_grass_name = "grass" in layer_name_lower
            has_shape_objects = any(getattr(obj, "image", None) is None for obj in layout)
            
            if has_spawner_name:
                # Process spawner layer
                if hasattr(self, 'spawner'):
                    self.create_spawner_layer(layout)
                else:
                    _tmx_layout_log.debug(
                        "Warning: Spawner layer %r found but spawner not set. Skipping spawner processing.",
                        layer_name,
                    )
            elif has_item_name:
                self.create_item_object_layer(layout)
            elif has_grass_name:
                self.create_grass_object_layer(layout)
            elif has_effect_name or has_shape_objects:
                self.create_effect_layer(layout)
            else:
                self.create_object_layer(layout)
            
            
            
        
        
        
        items = []
        for sprite in self.obstacle_sprites:
            #left, top, width, height = sprite.rect
            #right = left + width
            #bottom = top + height
            
            if hasattr(sprite, "mask"):
                mask = sprite.mask
            else: mask = None
            
            item = HashableRect(sprite.rect, mask = mask)
            items.append(item)
            
        self.obstacle_quad_tree_manager = QuadTreeManager()
        self.obstacle_quad_tree = QuadTree(items = items,
                                           depth=8,
                                           bounding_rect=pygame.rect.Rect(0,0,self.csv_layout_width,self.csv_layout_height),
                                           manager = self.obstacle_quad_tree_manager ) # this would actually need the size of the map bounding_rect=(0, 0, HEIGHT, WIDTH)
        world_rect = pygame.rect.Rect(0, 0, self.csv_layout_width, self.csv_layout_height)
        self.entity_quad_tree_manager = None
        self.entity_quad_tree = MovingEntityBroadphaseAdapter(
            world_rect=world_rect,
            backend=self._entity_broadphase_backend(),
            grid_cell_size=self._entity_broadphase_grid_cell_size(),
        )
                

        
        
        if restart:
            self.start_map_layout(selected_player_info_dir = self.selected_player_info_dir,
                            TILESIZE = TILESIZE,
                            restore_persistent_enemies_callback=self.restore_persistent_enemies_callback,
                            initialize_map_items_callback=self.initialize_map_items_callback, 
                            daytime_layout=daytime_layout,
                            Player = Player,
                            prepared_daytimeoverlay = prepared_daytimeoverlay)
        

    
        
        if player_position:
        
            self.player.rect.topleft = player_position
            self.player.hitbox.topleft = player_position
            self.player.update(layout_switch = False,
                               QuadTree=self.obstacle_quad_tree,
                               entity_quad_tree= self.entity_quad_tree)
            self.visible_sprites.add(self.player) 

        # Rebuild ground surface after layout reload (needed for F5 restart)
        self.visible_sprites.ground_surface = None
        self.visible_sprites.create_ground_surface()

    def _entity_broadphase_backend(self):
        if self.benchmark_runtime.enabled:
            return self.benchmark_runtime.broadphase_backend
        return ENTITY_BROADPHASE_BACKEND

    def _entity_broadphase_grid_cell_size(self):
        if self.benchmark_runtime.enabled:
            return self.benchmark_runtime.grid_cell_size
        return ENTITY_BROADPHASE_GRID_CELL_SIZE

    def switch_entity_broadphase_backend(self, backend_name, grid_cell_size=None):
        if not isinstance(self.entity_quad_tree, MovingEntityBroadphaseAdapter):
            return

        current_items = []
        for sprite in self.visible_sprites.sprites():
            if isinstance(sprite, Entity):
                current_items.append(
                    HashableRect(
                        sprite.rect,
                        sprite.id,
                        sprite.direction,
                        getattr(sprite, "sprite_type", None),
                        getattr(sprite, "mask", None),
                    )
                )
        self.entity_quad_tree.set_backend(
            backend_name,
            current_items=current_items,
            grid_cell_size=grid_cell_size,
        )
        if self.benchmark_runtime.enabled:
            self.benchmark_runtime.broadphase_backend = self.entity_quad_tree.backend_name
            self.benchmark_runtime.grid_cell_size = getattr(
                self.entity_quad_tree,
                "grid_cell_size",
                self.benchmark_runtime.grid_cell_size,
            )
        _tmx_layout_log.debug(
            "Entity broadphase backend switched to %s (grid_cell_size=%s)",
            self.entity_quad_tree.backend_name,
            getattr(self.entity_quad_tree, "grid_cell_size", None),
        )
        
        
        
     