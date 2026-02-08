import pygame
import math
from Settings import TILESIZE, DEBUG_DRAW_MASKS, DEBUG_DRAW_EFFECT_RECTS
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from Entity import Entity
from AnimatedEnvironmentSprite import AnimatedEnvironmentSprite
import Torch

class YSortCameraGroup(pygame.sprite.Group):
    def __init__(self, ground_sprites, grass_manager,overhead_areas):
        super().__init__()
        self.display_surface = pygame.display.get_surface()
        self.window_width, self.window_height = self.display_surface.get_size()
        self.half_width = self.display_surface.get_size()[0] // 2
        self.half_height = self.display_surface.get_size()[1] // 2
                
                # Define the dimensions for the grass surface
        grass_width = self.display_surface.get_width() - (2 * TILESIZE)
        grass_height = self.display_surface.get_height() - (2 * TILESIZE)
        
        # Set up the grass surface as a subsurface of the display surface
        self.grass_surface = self.display_surface.subsurface( (TILESIZE, TILESIZE, grass_width, grass_height) )
        
        self.grass_half_width = self.grass_surface.get_width() // 2
        self.grass_half_height = self.grass_surface.get_height() // 2
        
        
        self.offset = pygame.math.Vector2()
        self.grass_offset = pygame.math.Vector2()
        self.ground_sprites = ground_sprites
        self.ground_surface = None
        self.create_ground_surface()
        self.grass_manager = grass_manager
        self.update_grass_with_wind_frequency = 5000
        self.wind_last_affected_grass = 0
        self.t=0 # forgrass rotaryfunctin, name it better.
        
        # Threading.
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.lock = Lock()
        
        self.overhead_areas = overhead_areas
        self.debug_effect_areas = []  # For debug visualization of effect collision rects
        
    
    #@profile
    def update_parallel(self, obstruction_quad_tree,entity_quad_tree, dt=None, weather=None, wind_force=(0, 0), num_threads=1, *args, **kwargs):
        #print("attempted parallel update")
        #sprites_in_view = self.get_sprites_in_view()
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

    def set_grass_render_window_size_with_timeofday(self,light_level):
        #print("light_level!")
        #print(light_level)
        if light_level <= 1 and light_level > 0.75:
                # Define the dimensions for the grass surface
            grass_width = self.display_surface.get_width() - (2 * TILESIZE)
            grass_height = self.display_surface.get_height() - (2 * TILESIZE)
            
            # Set up the grass surface as a subsurface of the display surface
            self.grass_surface = self.display_surface.subsurface( (TILESIZE, TILESIZE, grass_width, grass_height) )
            
            self.grass_half_width = self.grass_surface.get_width() // 2
            self.grass_half_height = self.grass_surface.get_height() // 2

        # if light_level <= 0.75 and light_level > 0.5:
        #         # Define the dimensions for the grass surface
        #     grass_width = self.display_surface.get_width() - (2.5 * TILESIZE)
        #     grass_height = self.display_surface.get_height() - (2.5 * TILESIZE)
            
        #     # Set up the grass surface as a subsurface of the display surface
        #     self.grass_surface = self.display_surface.subsurface( (TILESIZE*1.25, TILESIZE*1.25, grass_width, grass_height) )
            
        #     self.grass_half_width = self.grass_surface.get_width() // 2
        #     self.grass_half_height = self.grass_surface.get_height() // 2
            
        #print(light_level)
        if light_level <= 0.5 :
                # Define the dimensions for the grass surface
            grass_width = self.display_surface.get_width() - (3 * TILESIZE)
            grass_height = self.display_surface.get_height() - (3 * TILESIZE)
            
            # Set up the grass surface as a subsurface of the display surface
            self.grass_surface = self.display_surface.subsurface( (TILESIZE*1.5, TILESIZE*1.5, grass_width, grass_height) )
            
            self.grass_half_width = self.grass_surface.get_width() // 2
            self.grass_half_height = self.grass_surface.get_height() // 2
            
        #print(f"RESULTING WIDTH : {self.grass_half_width}")
            

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
            
        self.offset.x = player.rect.centerx - self.half_width 
        self.offset.y = player.rect.centery - self.half_height
        self.grass_offset.x = player.rect.centerx - self.grass_half_width 
        self.grass_offset.y = player.rect.centery - self.grass_half_height
        
        
        ground_rect = self.ground_surface.get_rect(topleft=(-self.offset.x, -self.offset.y))
        self.display_surface.blit(self.ground_surface, ground_rect.topleft)
        
        
        self.set_grass_render_window_size_with_timeofday( light_intensity )
            
        #print(f" dt : {self.t}")
        self.t += dt*1500*wind_intensity
        rot_function = lambda x, y: int(math.sin(self.t / 60 + x / 100) * 15)
        
        # if player on grass
        
        self.grass_manager.apply_force( player.rect.center , 25 , 20)
        
        
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
        
        # DEBUG: Draw effect collision rects in red to compare with visual circles
        if DEBUG_DRAW_EFFECT_RECTS:
            for effect_area in self.debug_effect_areas:
                if hasattr(effect_area, 'rect'):
                    # Draw rect outline in red
                    rect_screen = pygame.Rect(
                        effect_area.rect.x - self.offset.x,
                        effect_area.rect.y - self.offset.y,
                        effect_area.rect.width,
                        effect_area.rect.height
                    )
                    pygame.draw.rect(self.display_surface, (255, 0, 0), rect_screen, 2)  # Red outline, 2px thick
        
        # DEBUG: Draw masks for all entities and objects
        if DEBUG_DRAW_MASKS:
            # Draw player mask in green
            if hasattr(player, 'mask') and player.mask:
                mask_size = player.mask.get_size()
                rect_size = (player.rect.width, player.rect.height)
                
                # Draw rect outline in green (this is the full bounding box)
                player_rect_screen = pygame.Rect(
                    player.rect.x - self.offset.x,
                    player.rect.y - self.offset.y,
                    player.rect.width,
                    player.rect.height
                )
                pygame.draw.rect(self.display_surface, (255, 255, 0), player_rect_screen, 2)  # Yellow for rect
                
                # Draw mask overlay (semi-transparent green) - this shows actual collision pixels
                try:
                    mask_surface = player.mask.to_surface(setcolor=(0, 255, 0, 128), unsetcolor=(0, 0, 0, 0))
                    # Draw mask at the same position as rect (masks should match rect size)
                    mask_rect_screen = pygame.Rect(
                        player.rect.x - self.offset.x,
                        player.rect.y - self.offset.y,
                        mask_size[0],
                        mask_size[1]
                    )
                    self.display_surface.blit(mask_surface, mask_rect_screen.topleft, special_flags=pygame.BLEND_ALPHA_SDL2)
                    # Draw green outline around actual mask size
                    pygame.draw.rect(self.display_surface, (0, 255, 0), mask_rect_screen, 2)  # Green for mask
                    
                    # Debug: Print size mismatch if any (only once per frame to avoid spam)
                    if mask_size != rect_size:
                        print(f"WARNING: Player mask size {mask_size} != rect size {rect_size}")
                except Exception as e:
                    print(f"Error drawing player mask: {e}")
                    pass  # Fallback if to_surface fails
            
            # Draw masks for all other sprites (entities and obstacles)
            for sprite in self.sprites():
                if hasattr(sprite, 'mask') and sprite.mask and sprite != player:
                    sprite_rect_screen = pygame.Rect(
                        sprite.rect.x - self.offset.x,
                        sprite.rect.y - self.offset.y,
                        sprite.rect.width,
                        sprite.rect.height
                    )
                    # Draw rect outline in cyan for other entities
                    pygame.draw.rect(self.display_surface, (0, 255, 255), sprite_rect_screen, 1)
                    # Draw mask overlay (semi-transparent cyan)
                    try:
                        mask_surface = sprite.mask.to_surface(setcolor=(0, 255, 255, 64), unsetcolor=(0, 0, 0, 0))
                        self.display_surface.blit(mask_surface, sprite_rect_screen.topleft, special_flags=pygame.BLEND_ALPHA_SDL2)
                    except:
                        pass  # Fallback if to_surface fails

    

    #@profile
    
    def set_overhead_areas(self, overhead_areas):
        self.overhead_areas = overhead_areas
    
    def update(self, dt=None, weather=None, wind_force=(0, 0), *args, **kwargs):
        
        for sprite in self.sprites():
            if isinstance(sprite, AnimatedEnvironmentSprite):
                sprite.update(weather, self.display_surface)
            else:
                sprite.update(dt)
    #@profile
    def update_for_parallel(self,obstacle_quad_tree, entity_quad_tree, batch, dt=None,lock=None, weather=None, wind_force=(0, 0) , *args, **kwargs):
        updated_sprites = []
        for sprite in batch:
            if isinstance(sprite, AnimatedEnvironmentSprite):# at some point i was passing display to torch, kept this if incase for now.
                if isinstance(sprite,Torch):
                    sprite.update(weather)
                else:
                    sprite.update(weather)
            elif isinstance(sprite, Entity):
                sprite.update(dt=dt,
                              QuadTree= obstacle_quad_tree,
                              entity_quad_tree = entity_quad_tree)
            else:
                sprite.update(dt=dt)
            
            # Acquire the lock before updating shared resources
            lock.acquire()
            try:
                updated_sprites.append(sprite)
            finally:
                # Always release the lock, even if an exception occurs
                lock.release()
                
        return updated_sprites
                    
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