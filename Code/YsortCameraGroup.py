import hashlib
import pygame
import math
import time
from Settings import (
    TILESIZE,
    GRASS_VIEWPORT_PERCENT,
    GRASS_WIND_MODE,
    GRASS_GPU_INSTANCED,
    DEBUG_DRAW_MASKS,
    DEBUG_DRAW_EFFECT_RECTS,
    DEBUG_DRAW_FACTION_OUTLINES,
)
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from Entity import Entity
from AnimatedEnvironmentSprite import AnimatedEnvironmentSprite
from Torch import Torch
from benchmark_runtime import BENCHMARK_RUNTIME
from game_logging import get_debug_logger

_grass_log = get_debug_logger("grass")

_FEET_ROW_CACHE = {}  # id(image) -> (size, lowest_opaque_row); size guards id reuse


def _feet_row(image):
    """Lowest opaque row of `image` (the feet within the frame). Used to anchor the
    directional shadow at the feet, not the image's bottom edge — so a frame whose feet
    don't reach the bottom (e.g. an attack/step pose) doesn't detach from its shadow.
    Cached by id(image), validated by size. Falls back to image height if fully empty."""
    key = id(image)
    size = image.get_size()
    entry = _FEET_ROW_CACHE.get(key)
    if entry is None or entry[0] != size:
        rects = pygame.mask.from_surface(image).get_bounding_rects()
        row = max((r.bottom for r in rects), default=size[1])
        entry = (size, row)
        _FEET_ROW_CACHE[key] = entry
    return entry[1]

_KNOWN_FACTION_OUTLINE_COLORS = {
    "player": (72, 220, 120),
    "enemy": (255, 72, 72),
    "friendly": (90, 170, 255),
    "neutral": (220, 200, 90),
}


def _faction_outline_color(team_id):
    if team_id is None:
        return (160, 160, 160)
    sid = str(team_id)
    if sid in _KNOWN_FACTION_OUTLINE_COLORS:
        return _KNOWN_FACTION_OUTLINE_COLORS[sid]
    digest = hashlib.md5(sid.encode("utf-8")).digest()
    r, g, b = digest[0], digest[1], digest[2]
    return (max(72, r), max(72, g), max(72, b))


class YSortCameraGroup(pygame.sprite.Group):
    def __init__(self, ground_sprites, grass_manager, overhead_areas, backend=None):
        super().__init__()
        self.backend = backend
        self.window_width, self.window_height = self.backend.get_size()
        self.half_width = self.backend.get_size()[0] // 2
        self.half_height = self.backend.get_size()[1] // 2

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
        self.runtime_debug_faction_outlines = DEBUG_DRAW_FACTION_OUTLINES

    def _grass_benchmark_active(self):
        return BENCHMARK_RUNTIME.enabled and BENCHMARK_RUNTIME.grass_benchmark_enabled

    def _grass_wind_mode(self):
        if self._grass_benchmark_active():
            return BENCHMARK_RUNTIME.grass_wind_mode
        return GRASS_WIND_MODE

    def _grass_disturbance_enabled(self):
        if self._grass_benchmark_active():
            return BENCHMARK_RUNTIME.grass_disturbance_enabled
        return True

    def _grass_viewport_percent(self):
        if self._grass_benchmark_active():
            return BENCHMARK_RUNTIME.grass_viewport_percent
        return GRASS_VIEWPORT_PERCENT

    def _apply_grass_force(self, location, radius, dropoff):
        self.grass_manager.apply_force(location, radius, dropoff)
        if self._grass_benchmark_active():
            BENCHMARK_RUNTIME.metrics.record_grass_force_call()

    def _apply_grass_viewport(self):
        W, H = self.backend.get_size()
        p = self._grass_viewport_percent() / 100.0
        gw = max(1, int(W * p))
        gh = max(1, int(H * p))
        x = (W - gw) // 2
        y = (H - gh) // 2
        clip_rect = pygame.Rect(x, y, gw, gh).clip(pygame.Rect(0, 0, W, H))
        if self.backend.raw_surface is not None:
            # CPU: in-place subsurface — grass blits land directly on the framebuffer.
            self.grass_surface = self.backend.raw_surface.subsurface(clip_rect)
            self._grass_clip_rect = None
        else:
            # GPU: offscreen surface, composited explicitly after grass renders.
            self.grass_surface = pygame.Surface(clip_rect.size, pygame.SRCALPHA)
            self._grass_clip_rect = clip_rect
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
            self.backend.invalidate_texture(self.ground_surface)

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
    def custom_draw(self, player,dt, wind_intensity, light_intensity, camera_focus=None, shadow=None):
        
        if self.ground_surface is None:
            self.create_ground_surface()

        W, H = self.backend.get_size()
        self.window_width, self.window_height = W, H
        self.half_width = W // 2
        self.half_height = H // 2

        self.set_grass_render_window_size_with_timeofday(light_intensity)

        focus = camera_focus or player
        self.offset.x = focus.rect.centerx - self.half_width 
        self.offset.y = focus.rect.centery - self.half_height
        self.grass_offset.x = focus.rect.centerx - self.grass_half_width 
        self.grass_offset.y = focus.rect.centery - self.grass_half_height

        if self.ground_surface is not None:
            ground_rect = self.ground_surface.get_rect(topleft=(-self.offset.x, -self.offset.y))
            self.backend.blit(self.ground_surface, ground_rect.topleft, cache_key=id(self.ground_surface))
            
        # Shared wind mode keeps one base sway angle for visible grass; legacy mode
        # preserves the current position-dependent wave across the field.
        self.t += dt*120*wind_intensity
        if self._grass_wind_mode() == "shared_patch":
            shared_angle = int(math.sin(self.t / 60) * 15)
            rot_function = lambda x, y, angle=shared_angle: angle
        else:
            rot_function = lambda x, y: int(math.sin(self.t / 60 + x / 100) * 15)
        
        # if player on grass
        
        player_center = player.rect.center
        if self._grass_disturbance_enabled():
            if self.last_player_grass_force_center is None:
                self._apply_grass_force(player_center, 25, 20)
                self.last_player_grass_force_center = player_center
            else:
                dx = player_center[0] - self.last_player_grass_force_center[0]
                dy = player_center[1] - self.last_player_grass_force_center[1]
                if (dx * dx + dy * dy) >= self.grass_force_threshold_sq:
                    self._apply_grass_force(player_center, 25, 20)
                    self.last_player_grass_force_center = player_center
        else:
            self.last_player_grass_force_center = player_center
        
        
        #print( self.grass_offset )
        #print( self.offset )
        
        # Draw grass relative to player
        if self._grass_clip_rect is not None:
            # GPU mode: blit each tile directly to the backend — no intermediate surface.
            if not getattr(self, "_grass_path_logged", False):
                _grass_log.info(
                    "GPU grass path: %s",
                    "INSTANCED (per-blade shader)" if GRASS_GPU_INSTANCED else "bitmap tile-cache",
                )
                self._grass_path_logged = True
            clip_x, clip_y = self._grass_clip_rect.topleft
            started_at = time.perf_counter() if self._grass_benchmark_active() else None
            if GRASS_GPU_INSTANCED:
                # Phase A proof: per-blade rotation in the GPU shader, one instanced
                # draw for the whole field. Crude (no exact pivot/shading parity).
                if not self.backend.grass_atlas_ready:
                    self.backend.build_grass_atlas(self.grass_manager.ga.blades)
                rows, count, visible_tiles, custom_tiles = self.grass_manager.update_render_gpu_instanced(
                    self._grass_clip_rect.size, dt,
                    offset=(self.grass_offset.x, self.grass_offset.y),
                    screen_origin=(clip_x, clip_y),
                    rot_function=rot_function)
                self.backend.draw_grass_instances(rows, count, self.grass_manager.shade_amount)
            else:
                visible_tiles = 0
                custom_tiles = 0
                for tile_surf, (tx, ty), cache_key in self.grass_manager.update_render_gpu(
                        self._grass_clip_rect.size, dt,
                        offset=(self.grass_offset.x, self.grass_offset.y),
                        rot_function=rot_function):
                    self.backend.blit(tile_surf, (tx + clip_x, ty + clip_y), cache_key=cache_key)
                    visible_tiles += 1
                    if cache_key is None:
                        custom_tiles += 1
            if started_at is not None:
                BENCHMARK_RUNTIME.metrics.record_grass_update(
                    (time.perf_counter() - started_at) * 1000.0,
                    visible_tiles=visible_tiles,
                    custom_tiles=custom_tiles,
                )
        else:
            # CPU mode: existing pipeline — blit tiles to grass_surface subsurface.
            if self._grass_benchmark_active():
                started_at = time.perf_counter()
                grass_stats = self.grass_manager.update_render(self.grass_surface,
                                             dt,
                                             offset=(self.grass_offset.x,
                                                     self.grass_offset.y),
                                          rot_function=rot_function,
                                          collect_stats=True)
                BENCHMARK_RUNTIME.metrics.record_grass_update(
                    (time.perf_counter() - started_at) * 1000.0,
                    visible_tiles=(grass_stats or {}).get("visible_tiles", 0),
                    custom_tiles=(grass_stats or {}).get("custom_tiles", 0),
                )
            else:
                self.grass_manager.update_render(self.grass_surface,
                                                 dt,
                                                 offset=(self.grass_offset.x,
                                                         self.grass_offset.y),
                                              rot_function=rot_function)

        # Directional shadow pre-pass: dark sheared silhouettes on the ground, under all
        # sprites (drawn before them). shadow = (dir_x, dir_y, length_scale, strength).
        if shadow is not None and shadow[3] > 0 and hasattr(self.backend, "draw_shadow"):
            sdx, sdy, slen, sstr = shadow
            for sprite in self.sprites():
                if not getattr(sprite, "casts_shadow", False):
                    continue
                if getattr(sprite, "_uncacheable_image", False):
                    continue  # per-frame recolored frame -> no stable texture, skip
                img = sprite.image
                iw, ih = img.get_size()
                x0 = sprite.rect.left - self.offset.x
                # Anchor the shadow base at the frame's actual feet (lowest opaque row),
                # not the image's bottom edge — frames whose feet sit above the edge (a
                # lifted-foot/attack pose) would otherwise detach from their shadow.
                yb = sprite.rect.top - self.offset.y + _feet_row(img)
                reach = ih * slen
                if x0 > W + reach or x0 + iw < -reach or yb > H + reach or yb - ih < -reach:
                    continue  # off-screen
                sx = sdx * reach
                sy = sdy * reach
                corners = ((x0 + sx, yb + sy), (x0 + iw + sx, yb + sy), (x0 + iw, yb), (x0, yb))
                self.backend.draw_shadow(img, corners, id(img), sstr)

        player_drawn = False
        for sprite in sorted(self.sprites(), key=lambda sprite: sprite.rect.centery):
            #print(sprite)
            #print(dir(sprite))
            offset_pos = sprite.rect.topleft - self.offset
            # Sprites that rebuild self.image as a brand-new Surface on transitions
            # (lighting recolor, freeze/thaw) have no stable identity to cache against —
            # route them through the always-upload path, same as grass/overlays.
            cache_key = None if getattr(sprite, "_uncacheable_image", False) else id(sprite.image)
            self.backend.blit(sprite.image, offset_pos, cache_key=cache_key)
            if self._grass_disturbance_enabled() and hasattr(sprite, "monster_name"):
                if sprite.monster_name == 'raccoon':
                    self._apply_grass_force( sprite.rect.center , 110 , 40)
                    
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
                self.backend.blit(image_section, (area.x - self.offset.x, area.y - self.offset.y))
        
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
                    self.backend.draw_rect((255, 0, 0), rect_screen, 2)  # Red outline, 2px thick
        
        # Runtime debug mode: highlight player with a clear outline.
        if self.runtime_debug_player_highlight:
            player_center = (
                int(player.rect.centerx - self.offset.x),
                int(player.rect.centery - self.offset.y),
            )
            highlight_radius = max(24, int(max(player.rect.width, player.rect.height) * 0.75))
            self.backend.draw_circle((255, 255, 0), player_center, highlight_radius, 3)

        if self.runtime_debug_faction_outlines:
            for sprite in self.sprites():
                if not isinstance(sprite, Entity) or not hasattr(sprite, "hitbox"):
                    continue
                hb = sprite.hitbox
                rect_screen = pygame.Rect(
                    hb.x - self.offset.x,
                    hb.y - self.offset.y,
                    hb.width,
                    hb.height,
                )
                team_id = getattr(sprite, "team_id", None)
                self.backend.draw_rect(_faction_outline_color(team_id), rect_screen, 2)

    #@profile
    
    def set_overhead_areas(self, overhead_areas):
        self.overhead_areas = overhead_areas
    
    def update(self, dt=None, weather=None, wind_force=(0, 0), *args, **kwargs):
        
        for sprite in self.sprites():
            if isinstance(sprite, AnimatedEnvironmentSprite):
                sprite.update(weather, self.backend.raw_surface)
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
        screen_width, screen_height = self.backend.get_size()
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