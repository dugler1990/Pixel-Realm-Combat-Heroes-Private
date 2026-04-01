import pygame
import math
from Settings import TILESIZE, GRASS_VIEWPORT_PERCENT, DEBUG_DRAW_MASKS, DEBUG_DRAW_EFFECT_RECTS
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from Entity import Entity
from AnimatedEnvironmentSprite import AnimatedEnvironmentSprite
from Torch import Torch

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
        self.grass_force_threshold_sq = 10  # 4px movement threshold before re-applying player force
        
        # Threading.
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.lock = Lock()
        
        self.overhead_areas = overhead_areas
        self.debug_effect_areas = []  # For debug visualization of effect collision rects
        self.runtime_debug_effect_rects = DEBUG_DRAW_EFFECT_RECTS
        self.runtime_debug_player_highlight = DEBUG_DRAW_MASKS

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

        if self.ground_surface is not None:
            ground_rect = self.ground_surface.get_rect(topleft=(-self.offset.x, -self.offset.y))
            self.display_surface.blit(self.ground_surface, ground_rect.topleft)
            
        #print(f" dt : {self.t}")
        self.t += dt*60*wind_intensity
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
        
        # DEBUG: Draw effect collision rects in red to compare with visual circles
        if self.runtime_debug_effect_rects:
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
        
        # Runtime debug mode: highlight player with a clear outline.
        if self.runtime_debug_player_highlight:
            player_center = (
                int(player.rect.centerx - self.offset.x),
                int(player.rect.centery - self.offset.y),
            )
            highlight_radius = max(24, int(max(player.rect.width, player.rect.height) * 0.75))
            pygame.draw.circle(self.display_surface, (255, 255, 0), player_center, highlight_radius, 3)

    

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