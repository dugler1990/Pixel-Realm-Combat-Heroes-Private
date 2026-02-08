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
import json
import math

class LayoutManager:
    
    def __init__(self, 
                 selected_player_info_dir,
                 TILESIZE,
                 restore_persistent_enemies_callback=None,
                 initialize_map_items_callback=None
                 ):
        # This class manages layouts of a level with triggers and logs
        self.start_map_layout(selected_player_info_dir = selected_player_info_dir,
                        TILESIZE = TILESIZE,
                        restore_persistent_enemies_callback=restore_persistent_enemies_callback,
                        initialize_map_items_callback=initialize_map_items_callback)

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
        self.grass_manager = GrassManager(grass_path="../Graphics/Grass", tile_size=TILESIZE, stiffness=600, max_unique=3, place_range=[0, 1])
    
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
        self.entity_quad_tree.insert(obstacle_sprite, 
                                     alive = alive,
                                     remove_existing=remove_existing
                                     )
        
            # The above is quite confusing, the insert method actually doesnt insert if alive is false,
            # the insert method deletes every time, if remove_existing is true
            

    def remove_obstacle_sprite_from_quad_tree(self, obstacle_sprite):# not used at the moment
        # Remove the obstacle sprite from the quadtree
        self.obstacle_quad_tree.delete(obstacle_sprite)

    def set_player(self, player):
        """Sets the player object for layout interaction."""
        self.player = player
    def set_spawner(self, spawner, layout_callback_update_quad_tree):
        """Sets the Spawner object for enemy management."""
        self.spawner = spawner  
        self.spawner.set_layout_callback_update_quad_tree( layout_callback_update_quad_tree )


## Create ground sprites:

#self.tmx_ground_layers = [  x  for x in  self.tmxdata.layers if x.name.find("Tile")!=1 ]
    
    def create_ground_layer( self,tmx_ground_layer ):
            
        layer_number_posstart = str(tmx_ground_layer).find("[")
        layer_number_posend = str(tmx_ground_layer).find("]")  ## This is defo not ideal, its how i get layer pos atm
                                                                # no clearbetter way to do it , i could manage the ids of layers..
        layer_number = str(tmx_ground_layer)[layer_number_posstart+1:layer_number_posend]   
        layer_number = int(layer_number)-1
                                                       
        for tile in tmx_ground_layer.tiles():
            
            
           
            try:
                tile_properties = self.tmxdata.get_tile_properties(tile[0],tile[1],layer_number)
                valid_interaction_types = [tile_properties.get("valid_interaction_types")]
            except:
                valid_interaction_types = []
            gid = self.tmxdata.get_tile_gid(tile[0], tile[1], layer_number)
            print(f"tile:{tile}")
            print(gid)
            
            
            surface =  self.tmxdata.get_tile_image(tile[0],tile[1],layer_number)
            surface = surface.copy()
            
            if surface:  # Ensure surface is not None
                width, height = surface.get_size()  # Get original size
                print(f"Original Size: {width}x{height}")  # Debugging
            
                surface = pygame.transform.scale(surface, (TILESIZE, TILESIZE))
            
            # if surface:
            #     filename = f"tile_{tile[0]}_{tile[1]}.png"
            #     pygame.image.save(surface, filename)
            #     print(f"Saved tile ({tile[0]}, {tile[1]}) as {filename}")
            
            new_tile = Tile(pos = (tile[0]*TILESIZE,tile[1]*TILESIZE),# could refactor pos its used atleast twice here
                            groups = [self.ground_sprites],
                            sprite_type ='ground',
                            surface = surface, # only surface if imported with pygame func
                            valid_interaction_types = valid_interaction_types)
            
            self.tile_map[(tile[0], tile[1])] = new_tile
            
        
    def create_object_layer( self,tmx_object_layer ):
        
        ## Fix discrepancy between tiled map tilesize and game tilesize
        
        tiled_tile_width = self.tmxdata.tilewidth
        tiled_tile_height = self.tmxdata.tileheight
        
        for object_ in tmx_object_layer:
        
            image = object_.image

                
            x_pos = (object_.x*TILESIZE ) / tiled_tile_width
            y_pos = (object_.y*TILESIZE ) / tiled_tile_height
            

            width_scaling_factor = TILESIZE/tiled_tile_width
            height_scaling_factor = TILESIZE/tiled_tile_height
            
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
    
        # DEBUG: Log TMX position vs calculated position
        import os
        import math
        
        # Count mask pixels to verify ellipse is correct size
        mask_pixel_count = mask.count() if mask else 0
        expected_ellipse_area = math.pi * (surf_w / 2) * (surf_h / 2) if getattr(obj, "ellipse", False) else surf_w * surf_h
        log_path = os.path.join(os.path.dirname(__file__), "effect_position_debug.log")
        with open(log_path, "a") as f:
            f.write(f"Effect {layer_name}_{idx}:\n")
            f.write(f"  TMX raw: obj.x={obj.x}, obj.y={obj.y}, obj.width={obj.width}, obj.height={obj.height}\n")
            f.write(f"  Scaling: sx={sx}, sy={sy}, TILESIZE={self.TILESIZE}, tilewidth={tw}, tileheight={th}\n")
            f.write(f"  Calculated: x_game={x_game}, y_game={y_game}, w_game={w_game}, h_game={h_game}\n")
            f.write(f"  Final rect: {rect} (surf_w={surf_w}, surf_h={surf_h})\n")
            f.write(f"  Mask pixel count: {mask_pixel_count}, Expected ellipse area: {expected_ellipse_area:.1f}\n")
            f.write(f"  Mask size: {mask.get_size() if mask else 'None'}\n\n")
    
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
            print("Warning: Spawner not set, cannot process spawner layer")
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
                print(f"Warning: Spawner object missing required config properties, skipping")
                continue
            
            # Generate spawn_matrix from object dimensions
            spawn_matrix = self._generate_spawn_matrix(obj, tiled_tile_width, tiled_tile_height)
            
            # Convert coordinates and create object_info
            object_info = self._create_spawner_object_info(obj, tiled_tile_width, tiled_tile_height)
            
            # Add spawn area to spawner
            self.spawner.add_spawn_area(spawn_matrix, spawner_config, object_info)
    
    def _extract_spawner_config(self, props):
        """
        Extract spawner configuration from object properties.
        Returns dict with spawner config or None if required properties missing.
        """
        # Required properties
        if 'enemy_spawn_weights' not in props:
            return None
        
        # Handle enemy_spawn_weights - could be JSON string or dict
        enemy_spawn_weights = props.get('enemy_spawn_weights')
        if isinstance(enemy_spawn_weights, str):
            try:
                enemy_spawn_weights = json.loads(enemy_spawn_weights)
            except json.JSONDecodeError:
                print(f"Warning: Could not parse enemy_spawn_weights as JSON: {enemy_spawn_weights}")
                return None
        
        # Build spawner config dict
        config = {
            'enemy_spawn_weights': enemy_spawn_weights,
            'spawn_type': props.get('spawn_type', 'random_weights'),
            'frequency': props.get('frequency', 10000),  # Default 10 seconds
            'spawn_limit': props.get('spawn_limit', 60),
            'spawn_number': props.get('spawn_number', 1)
        }
        
        # Optional properties
        if 'distance' in props:
            config['distance'] = props.get('distance')
        if 'time_scaled' in props:
            config['time_scaled'] = props.get('time_scaled', False)
        if 'scale_type' in props:
            config['scale_type'] = props.get('scale_type')
        if 'scale_max' in props:
            config['scale_max'] = props.get('scale_max')
        
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
        Convert Tiled pixel coordinates to game tile coordinates.
        Returns object_info dict with x_pos and y_pos in tile coordinates.
        """
        # Convert Tiled pixel coordinates to tile coordinates
        x_pos_tiles = obj.x / tiled_tile_width
        y_pos_tiles = obj.y / tiled_tile_height
        
        object_info = {
            'x_pos': int(x_pos_tiles),
            'y_pos': int(y_pos_tiles)
        }
        
        return object_info

    
    


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
        
        self.tmx_ground_layers = [  x  for x in  self.tmxdata.layers if type(x).__name__.find("TileLayer") != -1 ]

        self.tmx_object_layers = [  x  for x in  self.tmxdata.layers if type(x).__name__.find("ObjectGroup") != -1 ]
        # NOTE : Becuase of how tiled tmx data structure works, an effect Layer is a Object Layer, so i just make sure name contains Effect
        #        and check within the ground layers loop which initialization method i should use



        ## I need to create the effect layers loops here.
        #  1. how do i identify them, it uses the name and find... its using the type actually, 
        #    -> Get the import going to check the name and usage.
                
            

        for layout in self.tmx_ground_layers:

            self.create_ground_layer(layout)            

        for layout in self.tmx_object_layers:
            # Check if layer name contains "Effect" OR if any object has no image (shape-based effects)
            layer_name = getattr(layout, "name", "")
            layer_name_lower = layer_name.lower()
            has_effect_name = layer_name.find("Effect") != -1
            has_spawner_name = layer_name_lower.find("spawner") != -1
            has_shape_objects = any(getattr(obj, "image", None) is None for obj in layout)
            
            if has_spawner_name:
                # Process spawner layer
                if hasattr(self, 'spawner'):
                    self.create_spawner_layer(layout)
                else:
                    print(f"Warning: Spawner layer '{layer_name}' found but spawner not set. Skipping spawner processing.")
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
        self.entity_quad_tree_manager = QuadTreeManager()
        self.entity_quad_tree = QuadTree(items = [],
                                           depth=8,
                                           bounding_rect=pygame.rect.Rect(0,0,self.csv_layout_width,self.csv_layout_height),
                                           manager = self.entity_quad_tree_manager ) # this would actually need the size of the map bounding_rect=(0, 0, HEIGHT, WIDTH)
                

        
        
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

        
        
        
     