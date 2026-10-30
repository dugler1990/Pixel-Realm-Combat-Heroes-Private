import hashlib
import os
import random
import pygame
import math
import time
from Settings import (
    TILESIZE,
    GROUND_CHUNK_SIZE,
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
from Support import mask_midbottom_world, sprite_feet_sort_y
from AnimatedEnvironmentSprite import AnimatedEnvironmentSprite
from Torch import Torch
from Building import VIEW_DOOR, VIEW_IN, VIEW_OUT
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
    def __init__(self, ground_sprites, grass_manager, overhead_areas, backend=None,
                 buildings=None, door_covers=None):
        super().__init__()
        self.backend = backend
        self.window_width, self.window_height = self.backend.get_size()
        self.half_width = self.backend.get_size()[0] // 2
        self.half_height = self.backend.get_size()[1] // 2

        self._apply_grass_viewport()
        
        
        self.offset = pygame.math.Vector2()
        self.grass_offset = pygame.math.Vector2()
        # Brief camera shake (meteor impacts, etc.) — applied on top of focus offset.
        self._shake_until_ms = 0
        self._shake_start_ms = 0
        self._shake_amp = 0.0
        self.ground_sprites = ground_sprites
        self.ground_surface = None
        # (col, row) -> surface, when GROUND_CHUNK_SIZE is set. Held for the lifetime of the
        # level: the backend caches textures by id(surface), so these must not be collected.
        self.ground_chunks = {}
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
        # Authored buildings; held by reference so the layout manager can refill the
        # same list on layout reload.
        self.buildings = buildings if buildings is not None else []
        # Door frames as (rect, surface, building), held by reference like buildings.
        self.door_covers = door_covers if door_covers is not None else []
        self.debug_effect_areas = []  # For debug visualization of effect collision rects
        self.runtime_debug_effect_rects = DEBUG_DRAW_EFFECT_RECTS
        self.runtime_debug_player_highlight = DEBUG_DRAW_MASKS
        self.runtime_debug_faction_outlines = DEBUG_DRAW_FACTION_OUTLINES
        self.height_overlay = None
        self.height_overlay_origin = (0, 0)

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

    def add_screen_shake(self, amplitude=18.0, duration_ms=420):
        """Kick a short camera shake; overlapping kicks keep the stronger amp."""
        now = pygame.time.get_ticks()
        amp = float(amplitude)
        duration_ms = max(1, int(duration_ms))
        until = now + duration_ms
        if amp >= self._shake_amp or until >= self._shake_until_ms:
            self._shake_amp = max(self._shake_amp, amp)
            self._shake_start_ms = now
            self._shake_until_ms = max(self._shake_until_ms, until)

    def _apply_screen_shake(self):
        now = pygame.time.get_ticks()
        if now >= self._shake_until_ms or self._shake_amp <= 0:
            self._shake_amp = 0.0
            return
        span = max(1, self._shake_until_ms - self._shake_start_ms)
        elapsed = now - self._shake_start_ms
        decay = 1.0 - elapsed / float(span)
        amp = self._shake_amp * max(0.0, decay)
        # Sine kick reads clearer than pure noise at low amplitudes.
        phase = elapsed * 0.055
        ox = math.sin(phase * 2.1) * amp
        oy = math.cos(phase * 2.7) * amp * 0.75
        self.offset.x += ox
        self.offset.y += oy
        self.grass_offset.x += ox
        self.grass_offset.y += oy

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
        if self.ground_chunks:
            # Every chunk the tile touches, not just one: a tile on a boundary lives in both.
            for surface, bounds in self.ground_chunks.values():
                if not bounds.colliderect(tile.rect):
                    continue
                surface.blit(tile.image, tile.rect.move(-bounds.x, -bounds.y))
                self.backend.invalidate_texture(surface)
            return
        if not self.ground_surface:
            self.create_ground_surface()
        else:
            # Redraw only the area of the changed tile
            self.ground_surface.blit(tile.image, tile.rect.move(-self.min_x, -self.min_y))
            self.backend.invalidate_texture(self.ground_surface)

    def _chunk_span(self, value):
        """Which chunk column/row a world coordinate falls in, relative to the ground origin."""
        return (value - self.min_x) // GROUND_CHUNK_SIZE, (value - self.min_y) // GROUND_CHUNK_SIZE

    def create_ground_chunks(self):
        """The ground cut into textures of at most GROUND_CHUNK_SIZE, instead of one.

        Same compositing as create_ground_surface, but into a grid. A sprite is blitted into
        every chunk it touches -- sprites do not align to the grid, and one straddling a
        boundary has to appear in both or a seam opens up.

        The chunks are then blitted once each, off screen, to force their upload. The backend
        uploads a large surface the first time it is drawn, so without this each chunk would
        upload the first time the player walked into it: a scatter of stalls through play
        rather than one cost at load, which would be worse than the single surface it replaces.
        """
        columns = math.ceil((self.max_x - self.min_x) / GROUND_CHUNK_SIZE)
        rows = math.ceil((self.max_y - self.min_y) / GROUND_CHUNK_SIZE)
        self.ground_chunks = {}
        for col in range(columns):
            for row in range(rows):
                left = self.min_x + col * GROUND_CHUNK_SIZE
                top = self.min_y + row * GROUND_CHUNK_SIZE
                width = min(GROUND_CHUNK_SIZE, self.max_x - left)
                height = min(GROUND_CHUNK_SIZE, self.max_y - top)
                if width <= 0 or height <= 0:
                    continue
                bounds = pygame.Rect(left, top, width, height)
                members = [s for s in self.ground_sprites if bounds.colliderect(s.rect)]
                if not members:
                    continue                       # nothing here, so no texture for it
                surface = pygame.Surface((width, height)).convert_alpha()
                surface.fill((0, 0, 0, 0))
                for sprite in members:
                    surface.blit(sprite.image, sprite.rect.move(-left, -top))
                self.ground_chunks[(col, row)] = (surface, bounds)

        # Warm-up: draw each chunk somewhere off screen so the upload happens now.
        for surface, _ in self.ground_chunks.values():
            self.backend.blit(surface, (-surface.get_width() - 1, -surface.get_height() - 1),
                              cache_key=id(surface))

        # The chunks are now the ground. A painted background is ~1 GB decoded and its
        # Tile was holding a second full copy for nothing: nothing reads it back -- chunks
        # are never rebuilt, and update_tile_on_ground_surface blits the changed tile's own
        # image. Keep the rect (already derived) and drop only the big ones; a 150 px tile
        # is cheap and may be re-blitted.
        self._release_composited_ground_images()

    # Anything at or above this is a painted map, not a tile.
    _RELEASE_GROUND_IMAGE_ABOVE_PX = 4 * 1024 * 1024

    def _release_composited_ground_images(self):
        placeholder = None
        for sprite in self.ground_sprites:
            image = getattr(sprite, "image", None)
            if image is None:
                continue
            w, h = image.get_size()
            if w * h < self._RELEASE_GROUND_IMAGE_ABOVE_PX:
                continue
            if placeholder is None:
                placeholder = pygame.Surface((1, 1), pygame.SRCALPHA)
            sprite.image = placeholder

    def create_ground_surface(self):
        if not self.ground_sprites:
            return
        self.min_x = min(sprite.rect.left for sprite in self.ground_sprites)
        self.max_x = max(sprite.rect.right for sprite in self.ground_sprites)
        self.min_y = min(sprite.rect.top for sprite in self.ground_sprites)
        self.max_y = max(sprite.rect.bottom for sprite in self.ground_sprites)

        width = self.max_x - self.min_x
        height = self.max_y - self.min_y

        if GROUND_CHUNK_SIZE:
            self.create_ground_chunks()
            return

        self.ground_surface = pygame.Surface((width, height)).convert_alpha()
        self.ground_surface.fill((0, 0, 0, 0))
        for sprite in self.ground_sprites:
            self.ground_surface.blit(sprite.image, sprite.rect.move(-self.min_x, -self.min_y))
    #@profile
    def custom_draw(self, player,dt, wind_intensity, light_intensity, camera_focus=None, shadow=None, mid_fx_draw=None):
        self._draw_player = player
        if self.ground_surface is None and not self.ground_chunks:
            self.create_ground_surface()

        W, H = self.backend.get_size()
        self.window_width, self.window_height = W, H
        self.half_width = W // 2
        self.half_height = H // 2

        self.set_grass_render_window_size_with_timeofday(light_intensity)

        focus = camera_focus or player
        # Hitbox is world-position authority; planted rect.center bobs with mask
        # height and would shake the camera. Fall back to rect when no hitbox.
        focus_hitbox = getattr(focus, "hitbox", None)
        fx = focus_hitbox.centerx if focus_hitbox is not None else focus.rect.centerx
        fy = focus_hitbox.centery if focus_hitbox is not None else focus.rect.centery
        self.offset.x = fx - self.half_width
        self.offset.y = fy - self.half_height
        self.grass_offset.x = fx - self.grass_half_width
        self.grass_offset.y = fy - self.grass_half_height
        self._apply_screen_shake()

        if self.ground_chunks:
            # Only the chunks the camera can see. cache_key stays id(surface) to match
            # backend.invalidate_texture, which looks the cache up that way.
            view = pygame.Rect(self.offset.x, self.offset.y, self.window_width, self.window_height)
            for surface, bounds in self.ground_chunks.values():
                if not view.colliderect(bounds):
                    continue
                self.backend.blit(surface, (bounds.x - self.offset.x, bounds.y - self.offset.y),
                                  cache_key=id(surface))
        elif self.ground_surface is not None:
            ground_rect = self.ground_surface.get_rect(topleft=(-self.offset.x, -self.offset.y))
            self.backend.blit(self.ground_surface, ground_rect.topleft, cache_key=id(self.ground_surface))

        if self.height_overlay is not None:
            ox, oy = self.height_overlay_origin
            ow, oh = self.height_overlay.get_size()
            bounds = pygame.Rect(ox, oy, ow, oh)
            view = pygame.Rect(self.offset.x, self.offset.y, self.window_width, self.window_height)
            if view.colliderect(bounds):
                self.backend.blit(
                    self.height_overlay,
                    (ox - self.offset.x, oy - self.offset.y),
                    cache_key=id(self.height_overlay),
                )
            
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

        self._update_buildings(focus, dt)
        self._draw_building_interiors()
        # Buildings the subject is inside and seeing from: bodies on their floor out of
        # sight are not drawn, shadows included.
        lit = self._lit_buildings()

        # Directional shadow pre-pass: dark sheared silhouettes on the ground, under all
        # sprites (drawn before them). shadow = (dir_x, dir_y, length_scale, strength).
        if shadow is not None and shadow[3] > 0 and hasattr(self.backend, "draw_shadow"):
            sdx, sdy, slen, sstr = shadow
            for sprite in self.sprites():
                if not getattr(sprite, "casts_shadow", False):
                    continue
                if lit and self._out_of_sight(sprite, focus, lit):
                    continue
                if getattr(sprite, "mesh_boss", None) is not None:
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
        aerial_sprites = []
        for sprite in sorted(self.sprites(), key=sprite_feet_sort_y):
            #print(sprite)
            #print(dir(sprite))
            # Airborne VFX (e.g. descending meteors) skip ground Y-sort until late approach.
            if getattr(sprite, "draws_above_y_sort", False):
                aerial_sprites.append(sprite)
                continue
            if lit and self._out_of_sight(sprite, focus, lit):
                continue
            offset_pos = sprite.rect.topleft - self.offset
            self._draw_sorted_sprite(sprite, offset_pos)
            if self._grass_disturbance_enabled() and hasattr(sprite, "monster_name"):
                if sprite.monster_name == 'raccoon':
                    self._apply_grass_force( sprite.rect.center , 110 , 40)
        from mesh_boss import flush_body_mask_log
        flush_body_mask_log(pygame.time.get_ticks())

        if callable(mid_fx_draw):
            mid_fx_draw()

        self._draw_building_roofs(focus)

        # Overhead areas -- tree canopies and building doors -- over the player when he
        # is under one. After the roofs, not before: a roof drew over the canopy and the
        # roof pass then put the player back on top of it, so nothing could ever hide him
        # in a doorway. A canopy is above a roof anyway.
        for area, image_section in self.overhead_areas:
            if area.colliderect(player.rect):
                self.backend.blit(image_section, (area.x - self.offset.x, area.y - self.offset.y))

        # Door frames: over the player only once his feet are past the door line. Before
        # that he is in front of the door and is drawn over it -- covering him whenever his
        # box touched the frame's box hid his head while he was still walking up to it.
        hitbox = getattr(player, "hitbox", None)
        feet = hitbox.midbottom if hitbox is not None else player.rect.midbottom
        for area, image_section, building in self.door_covers:
            if area.colliderect(player.rect) and building.depth(feet) >= 0:
                self.backend.blit(image_section, (area.x - self.offset.x, area.y - self.offset.y))

        # Sky layer: descending rocks (and similar) over units / roofs while still high.
        for sprite in aerial_sprites:
            offset_pos = sprite.rect.topleft - self.offset
            self._draw_sorted_sprite(sprite, offset_pos)

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

    def set_buildings(self, buildings):
        self.buildings = buildings

    def _update_buildings(self, focus, dt):
        """Latch each building from the camera subject's feet.

        The subject, not the player: with an RTS camera on a worker, probing the
        player would open the building the hero happens to be standing in, off screen.
        Hitbox rather than rect because a planted rect bobs with mask height (the same
        reason camera focus reads the hitbox), and testing the rect would trip the
        cutaway as soon as the sprite's head overlapped a wall.
        """
        if not self.buildings:
            return
        hitbox = getattr(focus, "hitbox", None)
        feet = hitbox.midbottom if hitbox is not None else focus.rect.midbottom
        for building in self.buildings:
            building.update(dt, feet)

    def _draw_building_interiors(self):
        """Interior floors, under every sprite.

        Sits after grass on purpose: grass blits straight to the backend further up, so
        drawing this in the height_overlay slot would grow grass on the interior floor.

        Inside a building with sight, the chamber is drawn black and the interior again
        through the fan the subject sees, both from resident textures, so a moving fan
        uploads nothing. Under the sprites, not over them: a body whose feet are seen is
        drawn whole, and the sprite pass leaves out the ones whose feet are not.
        """
        if not self.buildings:
            return
        view = pygame.Rect(self.offset.x, self.offset.y, self.window_width, self.window_height)
        for building in self.buildings:
            if building.view == VIEW_OUT or not view.colliderect(building.footprint):
                continue
            dest = (building.footprint.x - self.offset.x, building.footprint.y - self.offset.y)
            sight = getattr(building, "sight", None)
            if building.view == VIEW_IN and sight is not None and sight.active:
                self.backend.blit(
                    sight.black,
                    (sight.black_rect.x - self.offset.x, sight.black_rect.y - self.offset.y),
                    cache_key=id(sight.black),
                )
                self.backend.blit_fan(
                    building.interior, dest,
                    (sight.origin[0] - self.offset.x, sight.origin[1] - self.offset.y),
                    sight.ring - (self.offset.x, self.offset.y),
                    cache_key=id(building.interior),
                )
                continue
            self.backend.blit(building.interior, dest, cache_key=id(building.interior))

    def _lit_buildings(self):
        """The buildings whose floor is only seen through the subject's fan."""
        return [building for building in (self.buildings or ())
                if getattr(building, "sight", None) is not None and building.sight.active]

    def _out_of_sight(self, sprite, focus, lit):
        """Is `sprite` on a lit building's floor where the subject cannot see it?

        By its feet, the way the roof pass decides who is on a floor: a body whose feet are
        seen is drawn whole, head over the wall and all, and one whose feet are not is not
        drawn at all -- not even what of it sticks up over lit stone. The subject itself is
        always drawn.
        """
        if sprite is focus:
            return False
        hitbox = getattr(sprite, "hitbox", None)
        feet = hitbox.midbottom if hitbox is not None else sprite.rect.midbottom
        for building in lit:
            if building.contains(feet) and not building.sight.sees(feet):
                return True
        return False

    def _draw_building_roofs(self, focus):
        """Roofs, over every sprite. Inside: baked chamber cutaway. Door: arch split.

        Drawn whenever on screen — never gated on overlapping the player the way canopy
        is — because a roof is simply how the building looks. The cutaway is the room.
        """
        if not self.buildings:
            return
        view = pygame.Rect(self.offset.x, self.offset.y, self.window_width, self.window_height)
        for building in self.buildings:
            if not view.colliderect(building.footprint):
                continue
            dest = (building.footprint.x - self.offset.x, building.footprint.y - self.offset.y)
            if building.view == VIEW_IN:
                self.backend.blit(
                    building.roof_inside, dest, cache_key=id(building.roof_inside))
            elif building.view == VIEW_DOOR:
                self.backend.blit(building.roof, dest, cache_key=id(building.roof))
                self.backend.blit(
                    building.interior, dest, cache_key=id(building.interior))
                self.backend.blit(
                    building.roof_open, dest, cache_key=id(building.roof_open))
                patch = building.far_arch_patch()
                if patch is not None:
                    surface, world_pos = patch
                    self.backend.blit(
                        surface,
                        (world_pos[0] - self.offset.x, world_pos[1] - self.offset.y),
                        cache_key=None,
                    )
            else:
                self.backend.blit(building.roof, dest, cache_key=id(building.roof))
        self._draw_sprites_over_roofs()

    def _draw_sprites_over_roofs(self):
        """Roofs draw after every sprite, so a body in front of one would vanish under stone.

        Re-blit anyone standing in front of a building (higher world-Y, toward the
        camera). Anyone on a building's floor is NOT re-blitted: the hole in the roof is
        their window, and the roof around it -- the pyramid's own face -- hides whatever
        of them sticks out past the room. Behind the building they stay under.
        """
        if not self.buildings:
            return
        for sprite in self.sprites():
            hitbox = getattr(sprite, "hitbox", None)
            feet = hitbox.midbottom if hitbox is not None else sprite.rect.midbottom
            if not self._roof_would_cover(sprite.rect, feet):
                continue
            offset_pos = sprite.rect.topleft - self.offset
            self._draw_sorted_sprite(sprite, offset_pos)

    def _draw_sorted_sprite(self, sprite, offset_pos):
        """Mesh boss when present, otherwise the sprite blit. Mesh is drawn at the feet."""
        boss = getattr(sprite, "mesh_boss", None)
        if boss is not None:
            hitbox = getattr(sprite, "hitbox", None)
            if getattr(sprite, "sprite_anchor_px", None) is not None and hitbox is not None:
                feet = hitbox.midbottom
            elif getattr(sprite, "mask", None) is not None:
                feet = mask_midbottom_world(sprite.rect, sprite.mask)
            elif hitbox is not None:
                feet = hitbox.midbottom
            else:
                feet = sprite.rect.midbottom
            screen_pos = (feet[0] - self.offset.x, feet[1] - self.offset.y)
            facing = getattr(sprite, "get_facing_deg", None)
            facing_deg = facing() if callable(facing) else 0.0
            height_px = getattr(sprite, "mesh_height_px", 650)
            if boss.draw(self.backend, screen_pos, facing_deg, height_px):
                if os.environ.get("PRCH_SHOW_BODY", "0") == "1":
                    self._draw_body_outline(sprite, screen_pos)
                return
        cache_key = None if getattr(sprite, "_uncacheable_image", False) else id(sprite.image)
        self.backend.blit(sprite.image, offset_pos, cache_key=cache_key)

    def _draw_body_outline(self, sprite, screen_pos):
        """Stroke ground-frame capsules when PRCH_SHOW_BODY=1.

        Green: not touching the local player. Red: capsules in a_hits.
        Also draws the local player's upright capsule.
        """
        import math
        import numpy as np
        from Settings import VIEW_ELEVATION_DEG
        import body_contact
        from body_contact import ground_to_screen, model_to_ground

        boss = getattr(sprite, "mesh_boss", None)
        if boss is None:
            return
        E = VIEW_ELEVATION_DEG
        height_px = float(getattr(sprite, "mesh_height_px", 650) or 650)
        scale = height_px / max(boss.pack.height_units, 1e-6)
        get_facing = getattr(sprite, "get_facing_deg", None)
        facing = float(get_facing()) if callable(get_facing) else 0.0
        A_m, B_m = boss.pack.posed_capsule_ends(boss.frame_index)
        Ag = model_to_ground(A_m, boss.pack.pivot, facing, scale)
        Bg = model_to_ground(B_m, boss.pack.pivot, facing, scale)
        radii = boss.pack.capsule_radii * scale

        a_hits = None
        player = getattr(self, "_draw_player", None)
        if player is not None:
            c = body_contact.mesh_contact(
                body_contact.collision_body(sprite, E),
                body_contact.collision_body(player, E),
                E,
            )
            a_hits = c.a_hits

        def _stadium_outline(surf, a, b, radius, rgba):
            ax, ay = float(a[0]), float(a[1])
            bx, by = float(b[0]), float(b[1])
            r = max(1, int(round(float(radius))))
            pygame.draw.circle(surf, rgba, (int(round(ax)), int(round(ay))), r, 1)
            pygame.draw.circle(surf, rgba, (int(round(bx)), int(round(by))), r, 1)
            dx = bx - ax
            dy = by - ay
            length = math.hypot(dx, dy)
            if length < 1e-6:
                return
            nx = -dy / length * float(radius)
            ny = dx / length * float(radius)
            pygame.draw.line(
                surf, rgba,
                (int(round(ax + nx)), int(round(ay + ny))),
                (int(round(bx + nx)), int(round(by + ny))),
                1,
            )
            pygame.draw.line(
                surf, rgba,
                (int(round(ax - nx)), int(round(ay - ny))),
                (int(round(bx - nx)), int(round(by - ny))),
                1,
            )

        sa = ground_to_screen(Ag, E)
        sb = ground_to_screen(Bg, E)
        pad = int(math.ceil(float(radii.max()) + 2.0)) if radii.size else 2
        xs = np.concatenate([sa[:, 0], sb[:, 0]])
        ys = np.concatenate([sa[:, 1], sb[:, 1]])
        x0 = float(xs.min()) - pad
        y0 = float(ys.min()) - pad
        w = max(1, int(math.ceil(xs.max() - x0 + pad)))
        h = max(1, int(math.ceil(ys.max() - y0 + pad)))
        surf = pygame.Surface((w, h), flags=pygame.SRCALPHA)
        for i in range(len(radii)):
            hit = bool(a_hits[i]) if a_hits is not None and i < len(a_hits) else False
            rgba = (255, 40, 40, 220) if hit else (0, 255, 80, 220)
            _stadium_outline(
                surf,
                (sa[i, 0] - x0, sa[i, 1] - y0),
                (sb[i, 0] - x0, sb[i, 1] - y0),
                radii[i],
                rgba,
            )
        dest = (int(screen_pos[0] + x0), int(screen_pos[1] + y0))
        self.backend.blit(surf, dest, cache_key=None)

        if player is None:
            return
        pb = body_contact.collision_body(player, E)
        # Player feet screen = player hitbox midbottom minus camera offset
        p_feet = player.hitbox.midbottom
        p_screen = (p_feet[0] - self.offset.x, p_feet[1] - self.offset.y)
        # Capsules are absolute ground; convert relative to player feet ground
        rel_a = pb.A.copy()
        rel_b = pb.B.copy()
        rel_a[:, 0] -= pb.feet[0]
        rel_a[:, 1] -= pb.feet[1]
        rel_b[:, 0] -= pb.feet[0]
        rel_b[:, 1] -= pb.feet[1]
        psa = ground_to_screen(rel_a, E)
        psb = ground_to_screen(rel_b, E)
        pr = float(pb.R[0]) if pb.R.size else 8.0
        pad = int(math.ceil(pr + 2.0))
        xs = np.concatenate([psa[:, 0], psb[:, 0]])
        ys = np.concatenate([psa[:, 1], psb[:, 1]])
        x0 = float(xs.min()) - pad
        y0 = float(ys.min()) - pad
        w = max(1, int(math.ceil(xs.max() - x0 + pad)))
        h = max(1, int(math.ceil(ys.max() - y0 + pad)))
        surf = pygame.Surface((w, h), flags=pygame.SRCALPHA)
        _stadium_outline(
            surf,
            (psa[0, 0] - x0, psa[0, 1] - y0),
            (psb[0, 0] - x0, psb[0, 1] - y0),
            pr,
            (0, 220, 255, 220),
        )
        dest = (int(p_screen[0] + x0), int(p_screen[1] + y0))
        self.backend.blit(surf, dest, cache_key=None)


    def _roof_would_cover(self, sprite_rect, feet):
        """Should this body be drawn again on top of the roofs?

        Under wins over in-front: the re-blit draws the body over EVERY roof, so one
        building that wants it under its roof vetoes, whatever a neighbouring footprint
        the rect also touches would say. "In front" is feet below the building's centre
        -- right for south-facing doors; approaching a north door you are behind the face.
        """
        in_front = False
        for building in self.buildings:
            if not sprite_rect.colliderect(building.footprint):
                continue
            if building.view == VIEW_DOOR:
                return True                      # wedge: the sliver reveals the body
            if building.contains(feet):
                return False                     # on the floor: seen through the hole only
            if feet[1] >= building.footprint.centery:
                in_front = True
        return in_front
    
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