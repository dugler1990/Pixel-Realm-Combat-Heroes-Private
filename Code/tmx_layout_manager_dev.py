#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Feb  8 01:03:00 2025

@author: fresh
"""
import pytmx

map1 = pytmx.TiledMap("map1.tmx")




# with pygame
import pygame
from pytmx.util_pygame import load_pygame

screen = pygame.display.set_mode((0,0))
tmxdata = load_pygame("../levels/tmx//map.tmx")

class LayoutManager:
    def __init__(self, 
                 selected_player_info_dir,
                 TILESIZE,
                 restore_persistent_enemies_callback=None,
                 initialize_map_items_callback=None
                 ):
        # This class manages layouts of a level with triggers and logs
        # #print(TILESIZE)        
        # self.TILESIZE = TILESIZE
    
        # self.restore_persistent_enemies_callback = restore_persistent_enemies_callback        
        # self.ground_sprites = pygame.sprite.Group()
        # self.selected_player_info_dir = selected_player_info_dir        
        # self.grass_manager = grass_manager = GrassManager(grass_path="../Graphics/Grass",
        #                                                   tile_size=TILESIZE,
        #                                                   stiffness=600,
        #                                                   max_unique=3, 
        #                                                   place_range=[0, 1])
        # #self.grass_manager.enable_ground_shadows(shadow_radius=4, shadow_color=(0, 0, 1), shadow_shift=(1, 2))
        # self.visible_sprites = YSortCameraGroup(self.ground_sprites, self.grass_manager)
        # self.obstacle_sprites = pygame.sprite.Group()
        # self.trigger_sprites = pygame.sprite.Group() 
        # self.animation_active = False    
        # self.player = None 
        # self.initialize_map_items_callback= initialize_map_items_callback
        # self.tile_map = {} 
        # self.daytime_brightness_overlay = DaytimeBrightnessOverlay()
        # Enable Ground Shadows
        #self.grass_manager.enable_ground_shadows(shadow_strength=40, shadow_radius=2, shadow_color=(0, 0, 1), shadow_shift=(0, 0))

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
        #print(f"resulting daytime overlay value : {self.daytime_brightness_overlay}")
    
    
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


    def trigger_animation(self, frames, position, speed):
        AnimationSprite(frames, position, speed, [self.visible_sprites])


    def set_spawner(self, spawner, layout_callback_update_quad_tree):
        """Sets the Spawner object for enemy management."""
        self.spawner = spawner  
        self.spawner.set_layout_callback_update_quad_tree( layout_callback_update_quad_tree )

    def add_item_visual(self, item):
        """Convert Item to ItemVisual and add to visible_sprites."""
         
        item_visual = ItemVisual(item=item, groups=[self.visible_sprites])
        
        #print(f"Item attempted to be added to visual sprites: {item_visual}")
        self.visible_sprites.add(item_visual)

    def initialize_layout(self,
                          layout_path,player_position=None,
                          restart = False, 
                          Player = None,
                          daytime_layout=False, 
                          prepared_daytimeoverlay = None):  

       #print(f"  Player position in initialize layout : {player_position}")
        
        self.spawner.spawn_areas = [] # each layout start fresh spawn areas if any.ofc.
        #print(f"starting layout : {layout_path}")        
        # Clear existing sprites from groups
        self.ground_sprites.empty()
        self.visible_sprites.empty()
        self.trigger_sprites.empty()
        self.obstacle_sprites.empty()
        self.last_trigger_time = None
        if restart:
            self.start_map_layout(selected_player_info_dir = self.selected_player_info_dir,
                            TILESIZE = TILESIZE,
                            restore_persistent_enemies_callback=self.restore_persistent_enemies_callback,
                            initialize_map_items_callback=self.initialize_map_items_callback, 
                            daytime_layout=daytime_layout,
                            Player = Player,
                            prepared_daytimeoverlay = prepared_daytimeoverlay)
        



        
        # Tile Layouts from .csv scaled tiles and dictionary.
        #print(os.listdir())
        #print(layout_path)

        layout_layers = os.listdir(layout_path)
        layout_layers = [layer for layer in layout_layers if '.' not in layer]
        for layer in layout_layers:
            #print("\n \n LAYER \n \n")
            #print(layer)
            if layer in ["Objects","Enemies","Items"]: continue
            with open(f"{layout_path}/{layer}/{layer}_layer_definition.json","r") as f : 
                layout_definition_dict = json.load(f)
            if os.path.exists(f"{layout_path}/{layer}/Objects" ):
                self.instantiate_objects( f"{layout_path}/{layer}/Objects" )
            if os.path.exists(f"{layout_path}/{layer}/Items"):
                item_config_path = f"{layout_path}/{layer}/Items/initial_map_items.json"
                if self.initialize_map_items_callback:
                    #print(f"item_config_path:{item_config_path}")
                    self.initialize_map_items_callback(item_config_path)

            
            self.instantiate_layout_layer( layout_definition_dict )
            
            self.visible_sprites.set_overhead_areas(self.overhead_areas)
                   
            # Instantiate Enemies
 
            #print(f"ATTEMPT TO DRAW ENEMIES FOR LAYER: {layout_path}")
            if os.path.exists(f"{layout_path}/{layer}/Enemies"):
                self.instantiate_enemies( f"{layout_path}/{layer}/Enemies", self.spawner )
            if os.path.exists(f"{layout_path}/{layer}/NeutralCharacters/NeutralCharacters.json"):
                self.instantiate_neutral_characters(f"{layout_path}/{layer}/NeutralCharacters/NeutralCharacters.json")
        
        # Use the callback to restore persistent enemies for the layout
        if self.restore_persistent_enemies_callback:
            self.restore_persistent_enemies_callback(layout_path)

        
        # Buildings and other sprites plus obstruction blocks
       
        # THIS IS FOR VERSION THAT HAS A SINGLE CENTRAL OBJECTS FOLDER AS IF IT WERE A LAYER ITSELF. ( ORIGINAL LEVEL 4 works like this (map4))
        #self.instantiate_objects( f"{layout_path}/Objects" )

    #print out the ground sprites details


        #print("\nGround Sprites:")
        #for sprite in self.ground_sprites:
           #print(f"Sprite: {sprite}, Position: {sprite.rect.topleft}, Size: {sprite.rect.size}")
          
            # Not sure about this.
            ## Not sure if i am re adding this actually.
            #self.obstacle_sprites.add(self.player)
            
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
            
        #print(f"items upon restart layout : {items}")
            
        #print(self.obstacle_sprites)
        #print("restarting quad trees :")
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
                

        #print(f"resulting changed quad trees  (should be empty): {self.entity_quad_tree.manager.item_mapping}")
        #print(f"resulting changed quad trees  (should be empty): {self.obstacle_quad_tree}")

        
        if player_position:
            #print(f"player_position in instantiate layout:{player_position}")
            # Reset player's directional attributes
            #self.player.direction.x = 0
            #self.player.direction.y = 0
        
            # Reset player's status to a known state
            #self.player.status = "down_idle"  # Or any other default idle state
        
            self.player.rect.topleft = player_position
            self.player.hitbox.topleft = player_position
            self.player.update(layout_switch = False,
                               QuadTree=self.obstacle_quad_tree,
                               entity_quad_tree= self.entity_quad_tree)
            self.visible_sprites.add(self.player) 


    def update_tile_image(self, key, position):
        """
        Update the image of a tile at the given position based on the provided key.
    
        :param key: A string key representing the new tile image to use.
        :param position: A tuple (x, y) representing the tile's position on the map.
        """
        # Define a dictionary mapping keys to their corresponding image paths
        image_mapping = {
            "building_in_progress": {"image_path":"../Graphics/Tiles/building_in_progress.png",
                                     "valid_interaction_types":[], 
                                      "is_obstacle" : True},
            "fishing_hole": {"image_path":"../Graphics/Tiles/fishing_hole.png",
                             "valid_interaction_types":[],
                              "is_obstacle" : True},
            "ice_tile":{"image_path":"../Graphics/Tiles/ice_tile.png",
                        "valid_interaction_types":["create_fishing_hole"],
                          "is_obstacle" : False} #### Should be a part of Tile.py really...maybe...            

                         }

        # Find the tile image path based on the provided key
        image_path = image_mapping.get(key).get("image_path")
        if not image_path:
            #print(f"No image found for key: {key}")
            return
        valid_interaction_types = image_mapping.get(key).get("valid_interaction_types")
        is_obstacle = image_mapping.get(key).get("is_obstacle")

        # Load the new image
        new_image = pygame.image.load(image_path).convert()
        new_image = pygame.transform.scale(new_image, (self.TILESIZE, self.TILESIZE))
        #print(f"position attempted to be found in update_tile_image : {position}")
        # Find the tile at the specified position
        tile = self.tile_map.get(position)
        
        if tile:
            # Remove the tile from all sprite groups to ensure the update is reflected
           
            groups = tile.groups()
            
            #print("Tile Groups")
            #print( groups )
            #print(" groups dir : ")
            #print( dir(groups[0]) )

            for group in groups:
                group.remove(tile)

            # Update the tile's image
            tile.image = new_image
            tile.valid_interaction_types = valid_interaction_types

            #print("Tile Groups")
            #print( groups )

            # Re-add the tile to all sprite groups
            for group in groups:
                #print(group)
                if group is self.obstacle_sprites:continue
                group.add(tile)

            if is_obstacle:
                # If the tile should be an obstacle, add it to the obstacle_sprites group
                self.obstacle_sprites.add(tile)

            
            # Update only the changed tile on the ground surface
            self.visible_sprites.update_tile_on_ground_surface(tile)

        else:
           #print(f"No tile found at position: {position}")
            pass




    def instantiate_objects(self, objects_path):
        # Check if the object_info.json file exists in the given objects_path
        object_info_path = os.path.join(objects_path, "object_info.json")
        if os.path.exists(object_info_path):
            # Open and read the object_info.json file
            with open(object_info_path, 'r') as file:
                objects_info = json.load(file)
        
            # Iterate over each object defined in the JSON file
           
            for obj_info in objects_info:
                object_image_path = obj_info.get("image_path")
                object_details = obj_info.get("object_info")
            
                # Assuming you have a function or method to handle the instantiation of an individual object
                self.instantiate_object(object_image_path, object_details)


    def instantiate_object(self, image_path, object_info):
        
        #print("creating object")
        
        image = pygame.image.load(image_path).convert_alpha()
        image_tile_width = object_info.get("width")
        image_tile_height = object_info.get("height")
        image = pygame.transform.scale(image, (self.TILESIZE * image_tile_width, self.TILESIZE * image_tile_height))
    
        image_x_pos = object_info.get("x_pos") * self.TILESIZE
        image_y_pos = object_info.get("y_pos") * self.TILESIZE
    
        # Dynamic handling based on type
        object_type = object_info.get("type",'')
        #print(f"object info:{object_info}")
        
        
        
        # TODO: SOLID principles issue, i do not want to adapt instantiate object when i create a new object,
        #       solution is to have if object_type is Animated Sprite, then it should instantiate_animatedsprite
        #       could just pass type to this and dynamically instantiate it .
        
        
        if object_type == "tree": 
            
            sprite_animation_config = object_info.get("sprite_animation_config")
            #print(f"ATTEMPTING TO CREATE TREE    config:{sprite_animation_config}")
            self.instantiate_tree(image_x_pos, image_y_pos, sprite_animation_config)
            
        elif object_type == "torch": 
            
            sprite_animation_config = object_info.get("sprite_animation_config")
            #print(f"ATTEMPTING TO CREATE TREE    config:{sprite_animation_config}")
            self.instantiate_torch(image_x_pos, image_y_pos, sprite_animation_config)
            
            
        else:
            Tile((image_x_pos, image_y_pos), [self.visible_sprites], "object", image)
    
        # Common methods for all objects
        self.handle_obstruction_matrix(image_x_pos,
                                       image_y_pos,
                                       object_info,
                                       image,
                                       mask_indicator=True)
        self.handle_spawn_area(image_x_pos, image_y_pos, object_info)
        self.handle_triggers(image_x_pos, image_y_pos, object_info)
    
    def instantiate_tree(self, x_pos, y_pos, sprite_animation_config):
        
        Tree((x_pos, y_pos), [self.visible_sprites, self.obstacle_sprites], sprite_animation_config)
        
    
    def instantiate_torch(self, x_pos, y_pos, sprite_animation_config):
        
        Torch((x_pos, y_pos), [self.visible_sprites, self.obstacle_sprites], sprite_animation_config)
       
    
    
    def handle_overhead_area(self,
                             x_pos,
                             y_pos,
                             object_info,
                             image,# TODO: not being passed......dno why its here, in below functino too 
                             tile_size_divisor):
        
        used_tile_size = self.TILESIZE / tile_size_divisor 
#        print(f"intiial overhead def : {object_info}")
        overhead_matrix = object_info.get("overhead_definition_path", [])
        
        if overhead_matrix != []:
            overhead_matrix = import_csv_layout(overhead_matrix)
            
        else:
            overhead_matrix = object_info.get('overhead_matrix',[])
        
        #print(f"overhead matrix: {overhead_matrix}")
        #print(f"dimensy :{len(overhead_matrix)}")
        y = -1 # TODO: unecessary , i just got a litttle lost, needs cleanup
        for y_ , row in enumerate( overhead_matrix ):
            y+=1
            x=-1
            #print(f"row : {overhead_matrix}")
            #print(f"row : {len(overhead_matrix)}")
            
            for x_ , cell in enumerate(row):
                x += 1
                #cell = cell[1]
                #print(f"cell : {cell}, type: {type(cell)}")
                if int(cell) == 1 :
                    
                    #print("hit on overhead_areas")
                    
                                        # Calculate the position of the overhead area
                    overhead_x = x_pos + (x * used_tile_size)
                    overhead_y = y_pos + (y * used_tile_size)
                    # Create a rect for the overhead area
                    overhead_rect = pygame.Rect(overhead_x+1, overhead_y+1, used_tile_size+1, used_tile_size+1)
                    # Extract the corresponding image section
                    image_section = image.subsurface(pygame.Rect((x * used_tile_size) +1, (y * used_tile_size) +1, used_tile_size+1, used_tile_size+1))
                    # Add the rect and image section to the overhead areas list
                    self.overhead_areas.append((overhead_rect, image_section))
        
    
    def handle_obstruction_matrix(self,
                                  x_pos,
                                  y_pos,
                                  object_info,
                                  image,
                                  tile_size_divisor=1,
                                  mask_indicator=False):
        
        

        
        used_tile_size = self.TILESIZE / tile_size_divisor # allows for smaller grain obstruction matrix
        obstacle_image = pygame.image.load( "../levels/Map4/ice_palace_2/ground/Objects/object_images/invisible_trigger.png" ).convert_alpha()
        obstacle_image = pygame.transform.scale( obstacle_image , (used_tile_size, used_tile_size) ) 
        #print("in obstruction matrix")
        
        
        ### Error is here, i was previously just getting attribute from object info, 
          # in the new use case for a scaled object, we are using .csvs just need a new if.
          # TODO This is a solid principles breach i think . interms of bad config...D?
        
        obstruction_matrix = object_info.get("csv_definition_path", [])
        
        if obstruction_matrix != []:
            obstruction_matrix = import_csv_layout(obstruction_matrix)
            
        else:
            obstruction_matrix = object_info.get('obstruction_matrix',[])
        
        #print(obstruction_matrix)
        #print(image.get_abs_offset())
        #print(image.get_size())
        #print(x_pos,y_pos)
        
        y_count = 0
        for y_offset, row in enumerate(obstruction_matrix, start=-1):
            y_count += 1
            x_count = 0
            for x_offset, cell in enumerate(row):
                x_count += 1
                if int(cell) == 1:
                    boundary_x = x_pos + (x_offset * used_tile_size)
                    boundary_y = y_pos + (y_offset * used_tile_size)
                    #print(boundary_x, boundary_y)
                    
                    
                    
                    #WL: STILL NO MICRO OBSTRUCTIONS HERE....
                    
                    
                    if mask_indicator:
                        mask = None
                        
                        
                        
                        #print(x_offset,y_offset)
                        #print(x_count,y_count)
                        mask_x =  (x_count -1) * used_tile_size 
                        mask_y  =  (y_count -1) * used_tile_size
                        
                        
                        #print(mask_x, mask_y)
                        # Define the ROI rectangle using the calculated top-left corner and TILESIZE
                        roi_rect = pygame.Rect(mask_x, mask_y , used_tile_size, used_tile_size)
                        
                        #print(roi_rect)
                        #print(dir(roi_rect))
                        
                        # Extract the portion of the image corresponding to the ROI
                        
                        
                        try: # TODO: we have this failing systematically if obstruction matrix is bigger than the size of the object, i dont really do this anyway tho.
                            # Create mask for the tile image
                            tile_image = image.subsurface(roi_rect)
                            mask = pygame.mask.from_surface(tile_image)
                        except:
                            mask = None
                    else:
                        mask = None
                    #print(boundary_x,boundary_y)
                    new_tile = Tile((boundary_x, boundary_y),
                                    [self.obstacle_sprites,self.ground_sprites], 
                                    'ground', # used to be insivible, checking effect
                                    mask = mask,
                                    surface = obstacle_image)
                    #self.add_obstacle_sprite_to_quad_tree(new_tile.rect) only creating QuadTree after initial layout initialization now
                    
    
    def handle_spawn_area(self, x_pos, y_pos, object_info):
        #print("in handlespawnarea")
        if object_info.get('spawn_area'):
            spawn_matrix = object_info.get("spawn_matrix")
            spawner_config_path = object_info.get("spawner_config_path")
            with open(spawner_config_path, 'r') as spawner_file:
                spawner_config = json.load(spawner_file)
                
            #print(f"spawner_config_path:{spawner_config_path}")
            #print(f"spawner_config:{spawner_config}")
            self.spawner.add_spawn_area(spawn_matrix, spawner_config, object_info)
    
    def handle_triggers(self, x_pos, y_pos, object_info):
        #print("in handle triggers")
        
        
        
        trigger_info = object_info.get("trigger_info", None)
        if trigger_info:
            #print(trigger_info)
            trigger_matrix = trigger_info.get("trigger_matrix", [])
            for y_offset, row in enumerate(trigger_matrix):
                for x_offset, cell in enumerate(row):
                    if cell == 1:
                        trigger_x = x_pos + (x_offset * self.TILESIZE)
                        trigger_y = y_pos + (y_offset * self.TILESIZE)
                        trigger = Trigger(trigger_x, trigger_y, self.TILESIZE, self.TILESIZE, trigger_info["destination_layout_path"], trigger_info["new_player_position"])
                        self.trigger_sprites.add(trigger)





    def instantiate_neutral_characters(self, neutral_char_path):
        
        #print("IN THE INSTANTIATE NEUTRAL CHAR LEVEL ")
        with open(neutral_char_path, 'r') as file:
            neutral_char_info = json.load(file)

        for char_def in neutral_char_info:
            char_type = char_def['type']
            positions = char_def['positions']
            attributes = char_def['attributes']

            # Use the Spawner to create neutral characters
            for pos in positions:
                # Prepare the config for the spawner
                config = {
                    'type': char_type,
                    'pos': pos,
                    'attributes': attributes
                }
                # Call the Spawner's method to spawn the neutral character
                self.spawner.spawn_neutral(config)


    
    def instantiate_enemies(self, enemy_path, spawner):


        # Check if the enemy directory exists
        if not os.path.exists(enemy_path):
            #print(f"No enemy directory found at {enemy_path}")
            return
        #print(f"{enemy_path}/enemies.json")
        with open( f"{enemy_path}/enemies.json", "r") as file:
            enemy_info = json.load(file)
            

        
        for enemy_def in enemy_info:
            #print(enemy_def)
            # Extract necessary information for spawning the enemy
            enemy_type = enemy_def.get('type')
            positions = enemy_def.get('positions', [])
            persistent = enemy_def.get('persistent', False)
            can_follow = enemy_def.get('can_follow', False)
            spawn_mode = enemy_def.get('spawn_mode', 'instant')  # Default spawn mode to 'instant'
            spawn_interval = enemy_def.get('spawn_interval', 0)
            spawn_chance = enemy_def.get('spawn_chance', 1.0)
            # Depending on the spawn mode, use the spawner to create enemies
            if spawn_mode == 'instant':
                for pos in positions:
                    spawn_cfg = {
                        'type': enemy_type,
                        'pos': pos,
                        'persistent': persistent,
                        'can_follow': can_follow,
                    }
                    if 'item_drop_info' in enemy_def:
                        spawn_cfg['item_drop_info'] = enemy_def['item_drop_info']
                    spawner.spawn_enemy(spawn_cfg)

            elif spawn_mode == 'timed':
                spawner.schedule_spawn(enemy_type, positions, spawn_interval, persistent, can_follow)
            elif spawn_mode == 'random':
                spawner.schedule_random_spawn(enemy_type, positions, spawn_chance, persistent, can_follow)
              



    def place_items_on_map(self, items_info):
        #print("IN PLACE ITEM ON MAP")
        for item_info in items_info:
            for position in item_info['positions']:  # Iterate over each position
                # Create an ItemVisual for each position and add it to visible_sprites
                item_visual = ItemVisual(item=item_info['item'], groups=[self.visible_sprites])
                # Convert the position from map grid coordinates to pixels
                item_visual.rect.topleft = (position[0] * self.TILESIZE, position[1] * self.TILESIZE)
                self.visible_sprites.add(item_visual)


    def instantiate_layout_layer(self, layout_definition_dict):
        
        #print(layout_definition_dict)

            
                
            
        layout_definition_dict = layout_definition_dict.get("layouts")
        for layout in layout_definition_dict:
            
            
            # if scaled image.
            layer_type = layout.get( 'layer_type', None )
            
            if layer_type == 'scaled_objects':
            
                scaled_objects = layout.get('scaled_objects',[])
                for object_ in scaled_objects:     
                    
                    image = pygame.image.load(object_.get('image_path')).convert_alpha()
                    image_tile_width = object_.get("width")
                    image_tile_height = object_.get("height")
                    image = pygame.transform.scale(image, (self.TILESIZE * image_tile_width, self.TILESIZE * image_tile_height))
                
                    image_x_pos = object_.get("x_pos") * self.TILESIZE
                    image_y_pos = object_.get("y_pos") * self.TILESIZE
                    
                    Tile((image_x_pos, image_y_pos), [self.ground_sprites], "ground", image)
                    #new_tile = Tile(pos, [self.ground_sprites], 'ground', tile_image, valid_interaction_types)
                    
                    
                    #### Urg , i need to fill in this somehow, i guess creating one big tile 
                    # will not work..
                    
                    # tile_grid[row_index][col_index] = new_tile
                    # self.tile_map[(pos[0], pos[1])] = new_tile
                    
                    ### Its how i draw ground tiles, right ? 
                    
                    
                    
                    obstruction_tile_size_divisor = object_.get( "tile_size_divisor" )
                    canopy_tile_size_divisor = object_.get( "canopy_size_divisor",1 )
                    # Common methods for all objects
                    self.handle_obstruction_matrix(image_x_pos,
                                                   image_y_pos,
                                                   object_,
                                                   image,
                                                   obstruction_tile_size_divisor)
                    self.handle_overhead_area(image_x_pos,
                                               image_y_pos,
                                               object_,
                                               image,
                                               canopy_tile_size_divisor
                                               )
                    self.handle_spawn_area(image_x_pos, image_y_pos, object_)
                    self.handle_triggers(image_x_pos, image_y_pos, object_)
            
            else:
                csv_layout_path = layout.get("csv_layout_path")
                layout_csv = import_csv_layout( csv_layout_path )
                
                sprite_group ='ground'
                tile_grid = [[None for _ in range(len(layout_csv[0]))] for _ in range(len(layout_csv))]  # Prepare a grid to store tile references
                #Note: separated water tiles bcoz they not ground sprites, they animated and we need to instantiate ground b4 animated sprites.
                water_tile_grid = [[None for _ in range(len(layout_csv[0]))] for _ in range(len(layout_csv))]  # Grid specifically for WaterTiles
                if not hasattr(self, "grass_tile_grid") :
                    self.grass_tile_grid = [[None for _ in range(len(layout_csv[0]))] for _ in range(len(layout_csv))]  # Grid specifically for GrassTiles
    
        
                #print(f" layout tiles ! : {layout.get('tiles', [])}")
                # First pass to create all tile instances
                
                #print(f"   HAS THE TILE SIZE CHANGE ????? : {self.TILESIZE}")
                for tile_info in layout.get("tiles", []):
                    
                    tile_image_path = tile_info.get("tile_image_path")
                    if tile_image_path != "irrelevant":
                        tile_image = pygame.image.load(tile_image_path).convert()
                        
                        
                        tile_image = pygame.transform.scale(tile_image, (self.TILESIZE, self.TILESIZE))
                        valid_interaction_types = tile_info.get("valid_interaction_types", [])
            
                    for row_index, row in enumerate(layout_csv):
                        for col_index, val in enumerate(row):
                            if val == str(tile_info["csv_constant_value"]):  # Match the CSV cell value
                                pos = (col_index * self.TILESIZE, row_index * self.TILESIZE)
                                if tile_info.get("type") == "water":
                                    #print(f"water vaid interacions : {valid_interaction_types}")
                                    animation_paths = tile_info.get('animation_config')
                                    # Initialize with a specific animation configuration
                                    animation_config = {
                                        'mild_ripple_neutral': import_folder( animation_paths.get('mild_ripple_neutral') ),
                                        'mild_ripple_left': import_folder(animation_paths.get('mild_ripple_left')),
                                        'mild_ripple_right': import_folder(animation_paths.get('mild_ripple_right')),
                                        'intense_ripple_left': import_folder(animation_paths.get('intense_ripple_left')),
                                        'intense_ripple_right': import_folder(animation_paths.get('intense_ripple_right')),
                                        'calm': import_folder( animation_paths.get('calm'))  # Default animation
                                    }
                                    new_tile = WaterTile(pos, [self.visible_sprites], animation_config, 150)
                                    water_tile_grid[row_index][col_index] = new_tile
                                    #new_tile = Tile(pos, [self.ground_sprites], 'ground', tile_image, valid_interaction_types)
                                    # For now always an obstruction
                                    # add regular water tile below:
                                    self.tile_map[(pos[0], pos[1])] = Tile(pos, [self.ground_sprites], 'ground', tile_image, valid_interaction_types)
                                    Tile(pos, [self.obstacle_sprites], 'invisible')
    #                                pass
                                elif tile_info.get("type") == "grass":
                                   
                                   grass_options = tile_info.get("grass_options", [0,1,2,3,4,5])
                                   grass_options = [0,1,2,3,4,5]
                                   grass_density = tile_info.get("grass_density", 0)
                                   grass_density = round(random.gauss(45, 8))
                                   
                                   self.grass_manager.place_tile(location=(col_index, row_index), density=grass_density, grass_options=grass_options)
                                   self.grass_tile_grid[row_index][col_index] = True
                               
                                elif tile_info.get("type") == "grass_big":
                                   
                                   grass_options = tile_info.get("grass_options", [6,7,8,9,10,11])
                                   grass_options = [6,7,8,9,10,11]
                                   grass_density = tile_info.get("grass_density", 0)
                                   grass_density = round(random.gauss(20, 6))
                                   
                                   self.grass_manager.place_tile(location=(col_index, row_index), density=grass_density, grass_options=grass_options)
                                   self.grass_tile_grid[row_index][col_index] = True
                                
                               
                                
                                else:
                                    # Create normal tiles
                                    new_tile = Tile(pos, [self.ground_sprites], 'ground', tile_image, valid_interaction_types)
                                    
                                    tile_grid[row_index][col_index] = new_tile
                                    self.tile_map[(pos[0], pos[1])] = new_tile  # Retain the mapping for all tiles
                    
                # Assign neighbors to WaterTiles after all tiles are instantiated
                for y in range(len(layout_csv)):
                    for x in range(len(layout_csv[0])):
                        if isinstance(water_tile_grid[y][x], WaterTile):
                            neighbors = {
                                'left': water_tile_grid[y][x - 1] if x > 0 and isinstance(water_tile_grid[y][x - 1], WaterTile) else None,
                                'right': water_tile_grid[y][x + 1] if x < len(water_tile_grid[0]) - 1 and isinstance(water_tile_grid[y][x + 1], WaterTile) else None,
                                'top': water_tile_grid[y - 1][x] if y > 0 and isinstance(water_tile_grid[y - 1][x], WaterTile) else None,
                                'bottom': water_tile_grid[y + 1][x] if y < len(water_tile_grid) - 1 and isinstance(water_tile_grid[y + 1][x], WaterTile) else None
                            }
                            water_tile_grid[y][x].adjacent_tiles = neighbors  # Update the WaterTile's neighbors
            
    
                self.visible_sprites.set_grass_grid(self.grass_tile_grid)



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
        #self.grass_manager = GrassManager(grass_path="../Graphics/Grass", tile_size=TILESIZE, stiffness=600, max_unique=3, place_range=[0, 1])
    
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

## Create ground sprites:

#self.tmx_ground_layers = [  x  for x in  self.tmxdata.layers if x.name.find("Tile")!=1 ]
self.tmx_map = map1
self.tmx_ground_layers = [  x  for x in  self.tmxdata.layers if type(x).__name__.find("TileLayer") != -1 ]
self.tmx_object_layers = [  x  for x in  self.tmxdata.layers if type(x).__name__.find("ObjectGroup") != -1 ]


def create_ground_layer( tmx_ground_layer ):
        
    
    layer_number_posstart = str(tmx_ground_layer).find("[")
    layer_number_posend = str(tmx_ground_layer).find("]")  ## This is defo not ideal, its how i get layer pos atm
                                                            # no clearbetter way to do it , i could manage the ids of layers..
    layer_number = str(tmx_ground_layer)[layer_number_posstart:layer_number_posend]     
                                                   
    for tile in tmx_ground_layer.tiles():
 
        new_tile = Tile(pos = pos,
                        groups = [self.ground_sprites],
                        sprite_type ='ground',
                        surface = tile[2], # only surface if imported with pygame func
                        valid_interaction_types = self.tmx_map.get_tile_properties(tile[0,tile[1]],layer_number))
        
        self.tile_map[(pos[0], pos[1])] = new_tile
        
    
def create_object_layer( tmx_object_layer ):
    
    for object_ in tmx_object_layer:
    
        image = object_.image
        mask = pygame.mask.from_surface(image)
        new_tile = Tile((boundary_x, boundary_y),
                        [self.obstacle_sprites,self.ground_sprites], 
                        'ground',
                        mask = mask,
                        surface = image)

def instantiate_layout_layer(self):
    
    for layout in self.tmx_ground_layers:
        self.create_ground_layer(layout)
    for layout in self.tmx_object_layers:
        self.create_ground_layer(layout)

        
        
        
        
     