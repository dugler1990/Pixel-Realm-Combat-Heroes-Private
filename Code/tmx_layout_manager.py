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
from Lighting import LightingManager
import pytmx
from YsortCameraGroup import YSortCameraGroup
from pytmx.util_pygame import load_pygame
from GrassManager import GrassManager
from QuadTree import QuadTree
from QuadTree import QuadTreeManager
from hashRect import HashableRect
from EffectArea import EffectArea
from effect_cell_grid import EffectCellGrid
from Torch import Torch
from Tree import Tree
from AnimationSprite import AnimationSprite
import copy
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
from InteractableChest import InteractableChest
from InteractableSeat import InteractableSeat
from navigation.walk_grid_cache import WalkGridCache
from rts.entities import DropoffBuilding, ResourceNode, RtsWorker
from rts.registry import RtsWorldRegistry
from rts.tmx_config import dropoff_config, resource_node_config
from tmx_layer_roles import LAYER_ROLES, dispatch_object_layer, resolve_layer_role
from sam3_obstacle_runtime import (
    CANOPY_OVERHEAD_RGBA,
    collision_mode_for_props,
    normalize_sam3_class,
    obstacle_surface_for_shape,
    split_trunk_canopy_masks,
    tint_rgba_for_class,
)
from Settings import DEBUG_DRAW_OBSTACLE_TINT

_tmx_layout_log = get_tmx_layout_logger()

# Legacy TMX: interactable_type=chest without interactable_profile uses this profile id,
# which maps to wooden chest type + default variant (paths under chests/wooden/default/ in JSON).
DEFAULT_CHEST_INTERACTABLE_PROFILE = "chest_default"

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
                 backend=None,
                 ):
        # This class manages layouts of a level with triggers and logs
        self.start_map_layout(selected_player_info_dir = selected_player_info_dir,
                        TILESIZE = TILESIZE,
                        restore_persistent_enemies_callback=restore_persistent_enemies_callback,
                        initialize_map_items_callback=initialize_map_items_callback,
                        backend=backend)
        self.benchmark_runtime = benchmark_runtime or BENCHMARK_RUNTIME

    def start_map_layout(self,
                         selected_player_info_dir,
                         TILESIZE,
                         restore_persistent_enemies_callback=None,
                         initialize_map_items_callback=None,
                         Player = None, 
                         daytime_layout = True,
                         prepared_daytimeoverlay = None,
                         backend=None):# this last param sucks, showing how bad my map change logic is.
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
        self.visible_sprites = YSortCameraGroup(
            self.ground_sprites, self.grass_manager, self.overhead_areas, backend=backend
        )
        self.environment_interactables = []
        self._env_interactable_profiles = {}
    
       # Positioning here again, its a bit of a mess , i think i do this in start map of level first and it gets reset here unwillingly so i set it again
       
        self.daytime_layout = daytime_layout
        # Set animation flag
        self.animation_active = False
    
    
        # Setup timer
        
        self.start_ticks = pygame.time.get_ticks()
        self._time_font = pygame.font.Font(None, 36)
        self._time_string = None
        self._time_surface = None
        

    
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

        # GPU day/night lighting (Phase L) — owns ambient + radial light sources,
        # replacing the flat brightness overlay's role in the tmx level loop.
        self.lighting = LightingManager() if self.daytime_layout else None
    
    
    
    
    def display_time(self, backend):
        # Calculate elapsed time in milliseconds
        elapsed_ticks = pygame.time.get_ticks() - self.start_ticks
        elapsed_seconds = elapsed_ticks // 1000
        minutes = elapsed_seconds // 60
        seconds = elapsed_seconds % 60
    
        # Format time as MM:SS
        time_string = f"{minutes:02}:{seconds:02}"

        if time_string != self._time_string:
            self._time_string = time_string
            self._time_surface = self._time_font.render(time_string, True, (255, 255, 255))

        backend.blit(self._time_surface, (backend.get_size()[0] / 2, 10))
    
    
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

    def _obstacle_quad_item_for_sprite(self, sprite, _id=-1):
        mask = sprite.mask if hasattr(sprite, "mask") else None
        return HashableRect(sprite.rect, _id=_id, mask=mask)

    def register_obstacle_sprite(self, sprite, *, live=False):
        """Convert an obstacle_sprites member to HashableRect; optionally register live."""
        existing = getattr(sprite, "_obstacle_quad_item", None)
        if existing is not None:
            return existing

        _id = -1
        if live:
            next_id = getattr(self, "_dynamic_obstacle_next_id", None)
            if next_id is None:
                next_id = -10000
            _id = next_id
            self._dynamic_obstacle_next_id = next_id - 1

        item = self._obstacle_quad_item_for_sprite(sprite, _id=_id)
        sprite._obstacle_quad_item = item

        if live:
            quad_tree = getattr(self, "obstacle_quad_tree", None)
            if quad_tree is not None:
                quad_tree.insert(item, alive=True, remove_existing=True)
            walk_cache = getattr(self, "walk_grid_cache", None)
            if walk_cache is not None:
                walk_cache.block_walk_grid_cells_for_item(item)

        return item

    def set_player(self, player):
        """Sets the player object for layout interaction."""
        self.player = player

    def trigger_animation(self, frames, position, speed, on_complete=None):
        AnimationSprite(frames, position, speed, [self.visible_sprites], on_complete=on_complete)

    def set_spawner(self, spawner, layout_callback_update_quad_tree):
        """Sets the Spawner object for enemy management."""
        self.spawner = spawner  
        self.spawner.set_layout_callback_update_quad_tree( layout_callback_update_quad_tree )

    def set_item_spawner(self, item_spawner):
        """ItemSpawner for TMX item layers and pickups (optional)."""
        self.item_spawner = item_spawner

    def add_item_visual(self, item):
        """Wrap Item in ItemVisual and add to visible_sprites. Returns the visual
        (co-op tags it with a drop_id for shared-loot sync)."""
        item_visual = ItemVisual(item=item, groups=[self.visible_sprites])
        self.visible_sprites.add(item_visual)
        return item_visual

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

    def _load_env_interactable_profiles(self, tmx_path):
        """Load env_interactable_profiles.json from layout folder first, else shared levels/tmx/."""
        self._env_interactable_profiles = {}
        candidates = []
        if tmx_path:
            candidates.append(
                os.path.normpath(
                    os.path.join(os.path.abspath(tmx_path), "env_interactable_profiles.json")
                )
            )
        _code_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(
            os.path.normpath(
                os.path.join(_code_dir, "..", "levels", "tmx", "env_interactable_profiles.json")
            )
        )
        for path in candidates:
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._env_interactable_profiles = data
                else:
                    _tmx_layout_log.debug(
                        "env_interactable_profiles.json must be a JSON object, got %s: %s",
                        type(data).__name__,
                        path,
                    )
            except (json.JSONDecodeError, OSError) as e:
                _tmx_layout_log.debug(
                    "Failed to load env interactable profiles from %s: %s", path, e
                )
            break
        else:
            _tmx_layout_log.debug(
                "No env_interactable_profiles.json found; world interactable profiles unavailable."
            )
        self._rebuild_chest_type_default_loot()

    def _rebuild_chest_type_default_loot(self):
        """
        Per material (wooden, metal, gold, ice): canonical default_loot from chest_{type}
        in JSON; wooden falls back to chest_default if chest_wooden has no default_loot.
        Used when chest_{type}_snow (or chest_{type}) has empty default_loot.
        """
        profiles = getattr(self, "_env_interactable_profiles", None) or {}
        self._chest_type_default_loot = {}
        for m in ("wooden", "metal", "gold", "ice"):
            prof = profiles.get(f"chest_{m}")
            dl = {}
            if prof and isinstance(prof.get("default_loot"), dict):
                dl = prof["default_loot"]
            if m == "wooden" and (not dl or len(dl) == 0):
                cd = profiles.get(DEFAULT_CHEST_INTERACTABLE_PROFILE, {})
                if isinstance(cd.get("default_loot"), dict) and len(cd["default_loot"]) > 0:
                    dl = cd["default_loot"]
            self._chest_type_default_loot[m] = copy.deepcopy(dl) if dl else {}

    def _merge_env_interactable_props(self, profile_id, props):
        """
        Merge profile defaults with TMX object properties.
        Returns a dict with kind, loot_info, interaction_margin, paths, profile_id, or None if unknown profile.
        """
        prof = self._env_interactable_profiles.get(profile_id)
        if not prof or not isinstance(prof, dict):
            _tmx_layout_log.debug(
                "Unknown interactable_profile=%r; add it to env_interactable_profiles.json",
                profile_id,
            )
            return None
        merged = copy.deepcopy(prof)
        merged["profile_id"] = profile_id

        loot_raw = props.get("loot_json")
        if isinstance(loot_raw, dict):
            loot_info = loot_raw
        else:
            try:
                loot_info = json.loads(loot_raw) if loot_raw else None
            except (json.JSONDecodeError, TypeError):
                loot_info = None
        if loot_info is not None and loot_info != {}:
            merged["loot_info"] = loot_info
        else:
            dl_raw = merged.get("default_loot") or {}
            if isinstance(dl_raw, dict) and len(dl_raw) > 0:
                merged["loot_info"] = copy.deepcopy(dl_raw)
            else:
                pid = merged.get("profile_id", "")
                bucket = getattr(self, "_chest_type_default_loot", None) or {}
                picked = None
                for m in ("wooden", "metal", "gold", "ice"):
                    if pid == f"chest_{m}_snow" or pid == f"chest_{m}":
                        picked = bucket.get(m)
                        break
                if picked is not None and isinstance(picked, dict) and len(picked) > 0:
                    merged["loot_info"] = copy.deepcopy(picked)
                else:
                    merged["loot_info"] = (
                        copy.deepcopy(dl_raw) if isinstance(dl_raw, dict) else {}
                    )
        merged.pop("default_loot", None)

        try:
            if props.get("interaction_margin") is not None and str(props.get("interaction_margin")).strip() != "":
                merged["interaction_margin"] = int(props.get("interaction_margin"))
        except (TypeError, ValueError):
            pass
        merged.setdefault("interaction_margin", 48)

        for tmx_key, merged_key in (
            ("open_animation", "open_animation_path"),
            ("image_open", "image_open_path"),
            ("hit_animation", "hit_animation"),
        ):
            raw = props.get(tmx_key)
            if raw is not None and str(raw).strip():
                merged[merged_key] = str(raw).strip()
            else:
                from_prof = prof.get(tmx_key) or prof.get(merged_key)
                if from_prof is not None and str(from_prof).strip():
                    merged[merged_key] = str(from_prof).strip()
                else:
                    merged[merged_key] = None

        merged.setdefault("kind", "loot_container")
        return merged

    def _scale_loot_chest_hit_frames(self, hit_frames, tw, th, sprite_fit):
        """
        Scale hit frames to fit the TMX object box in game pixels.
        pixel_contain (default): integer upscale when smaller than box (crisp pixel art),
        centered with topleft offset; downscale with aspect preserve if art is larger.
        stretch: scale exactly to (tw, th).
        Returns (scaled_frames, display_size (w,h), topleft_offset (dx,dy)).
        """
        sw, sh = hit_frames[0].get_size()
        fit = (sprite_fit or "pixel_contain").strip().lower()
        if fit == "stretch":
            scaled = [pygame.transform.scale(f, (tw, th)) for f in hit_frames]
            return scaled, (tw, th), (0, 0)
        if sw <= 0 or sh <= 0:
            scaled = [pygame.transform.scale(f, (tw, th)) for f in hit_frames]
            return scaled, (tw, th), (0, 0)
        k = min(tw // sw, th // sh)
        if k >= 1:
            nw, nh = sw * k, sh * k
            scaled = [pygame.transform.scale(f, (nw, nh)) for f in hit_frames]
        else:
            scale = min(float(tw) / float(sw), float(th) / float(sh))
            nw = max(1, int(round(sw * scale)))
            nh = max(1, int(round(sh * scale)))
            scaled = [pygame.transform.scale(f, (nw, nh)) for f in hit_frames]
        dx = (tw - nw) // 2
        dy = (th - nh) // 2
        return scaled, (nw, nh), (dx, dy)

    def _try_build_loot_chest_assets(self, merged, target_size=None):
        """
        Load hit animation frames; idle is the first frame (sorted order matches import_folder).
        If target_size is (w, h) with positive ints, scale frames per merged sprite_fit
        (default pixel_contain). Returns (idle_surface, hit_frames, layout_meta) or None;
        layout_meta: {"display_size": (w,h), "topleft_offset": (dx,dy)}.
        """
        from Support import import_folder, resolve_env_interactable_path

        pid = merged.get("profile_id", "?")
        tmx_folder = getattr(self, "tmx_folder", None)

        hit_raw = merged.get("hit_animation")
        if not hit_raw or not str(hit_raw).strip():
            _tmx_layout_log.error(
                "loot chest profile %r: missing hit_animation", pid
            )
            return None

        hit_path = resolve_env_interactable_path(str(hit_raw).strip(), tmx_folder)

        if not hit_path or not os.path.isdir(hit_path):
            _tmx_layout_log.error(
                "loot chest profile %r: hit_animation not a directory: %r (resolved %r)",
                pid,
                hit_raw,
                hit_path,
            )
            return None

        try:
            hit_frames = import_folder(hit_path)
        except Exception as e:
            _tmx_layout_log.error(
                "loot chest profile %r: failed to import hit frames from %r: %s",
                pid,
                hit_path,
                e,
            )
            return None

        if not hit_frames:
            _tmx_layout_log.error(
                "loot chest profile %r: hit_animation empty or unreadable: %r",
                pid,
                hit_path,
            )
            return None

        layout_meta = {"display_size": None, "topleft_offset": (0, 0)}
        if target_size is not None and len(target_size) >= 2:
            tw, th = int(target_size[0]), int(target_size[1])
            if tw > 0 and th > 0:
                sprite_fit = merged.get("sprite_fit")
                hit_frames, disp, off = self._scale_loot_chest_hit_frames(
                    hit_frames, tw, th, sprite_fit
                )
                layout_meta = {"display_size": disp, "topleft_offset": off}

        open_raw = merged.get("open_animation_path")
        open_path = None
        if open_raw and str(open_raw).strip():
            open_path = resolve_env_interactable_path(str(open_raw).strip(), tmx_folder)
        _tmx_layout_log.debug(
            "loot chest spawn profile=%r hit_animation_resolved=%r open_animation_resolved=%r",
            pid,
            hit_path,
            open_path,
        )

        idle_surface = hit_frames[0].copy()
        if layout_meta.get("display_size") is None:
            layout_meta = {
                "display_size": idle_surface.get_size(),
                "topleft_offset": (0, 0),
            }
        return (idle_surface, hit_frames, layout_meta)

    def _try_build_seat_assets(self, merged, target_size=None):
        """
        Load and scale seat idle sprite to TMX object size.
        Returns (idle_surface, layout_meta) or None on failure.
        """
        from Support import import_folder, resolve_env_interactable_path

        pid = merged.get("profile_id", "?")
        tmx_folder = getattr(self, "tmx_folder", None)
        idle_raw = merged.get("throne_idle")
        if not idle_raw or not str(idle_raw).strip():
            _tmx_layout_log.error(
                "seat profile %r: missing throne_idle", pid
            )
            return None
        idle_path = resolve_env_interactable_path(str(idle_raw).strip(), tmx_folder)
        if not idle_path:
            _tmx_layout_log.error(
                "seat profile %r: throne_idle could not be resolved from %r",
                pid,
                idle_raw,
            )
            return None

        idle_surface = None
        if os.path.isdir(idle_path):
            frames = import_folder(idle_path)
            if frames:
                idle_surface = frames[0].copy()
        elif os.path.isfile(idle_path):
            idle_surface = pygame.image.load(idle_path).convert_alpha()

        if idle_surface is None:
            _tmx_layout_log.error(
                "seat profile %r: throne_idle not readable: %r (resolved %r)",
                pid,
                idle_raw,
                idle_path,
            )
            return None

        layout_meta = {"display_size": idle_surface.get_size(), "topleft_offset": (0, 0)}
        if target_size is not None and len(target_size) >= 2:
            tw, th = int(target_size[0]), int(target_size[1])
            if tw > 0 and th > 0:
                sprite_fit = merged.get("sprite_fit")
                scaled_frames, disp, off = self._scale_loot_chest_hit_frames(
                    [idle_surface], tw, th, sprite_fit
                )
                idle_surface = scaled_frames[0]
                layout_meta = {"display_size": disp, "topleft_offset": off}

        return (idle_surface, layout_meta)

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
    
    def _process_tile_layer(self, tmx_ground_layer):
        from rts.build.sites_from_tiles import deep_snow_cell_from_props
        from tmx_tile_layers import tile_properties, tile_surface

        layer_name_lower = getattr(tmx_ground_layer, "name", "").lower()
        layer_has_grass = "grass" in layer_name_lower
        deep_snow_cells = {}

        for tile in tmx_ground_layer.tiles():
            tx, ty = tile[0], tile[1]
            tile_props = tile_properties(self.tmxdata, tmx_ground_layer, tx, ty)
            valid_interaction_types = [tile_props.get("valid_interaction_types")]

            fid = deep_snow_cell_from_props(tile_props)
            if fid is not None:
                deep_snow_cells[(tx, ty)] = fid

            surface = tile_surface(self.tmxdata, tmx_ground_layer, tx, ty)
            if not surface:
                continue
            surface = surface.copy()
            surface = pygame.transform.scale(surface, (TILESIZE, TILESIZE))

            new_tile = Tile(
                pos=(tx * TILESIZE, ty * TILESIZE),
                groups=[self.ground_sprites],
                sprite_type="ground",
                surface=surface,
                valid_interaction_types=valid_interaction_types,
            )
            self.tile_map[(tx, ty)] = new_tile

            if layer_has_grass:
                gp = tile_props.get("grass_profile")
                if gp is not None and str(gp).strip():
                    resolved = self._resolve_grass_profile(gp)
                    if resolved:
                        self.grass_manager.place_tile(location=(tx, ty), density=resolved)
                        grid = getattr(self, "grass_tile_grid", None)
                        if grid is not None and 0 <= ty < len(grid) and 0 <= tx < len(grid[0]):
                            grid[ty][tx] = True

        return deep_snow_cells

    def create_ground_layer(self, tmx_ground_layer):
        """Deprecated alias; use _process_tile_layer."""
        return self._process_tile_layer(tmx_ground_layer)

    def update_tile_image(self, key, position):
        """
        Update the image of a tile at the given position based on the provided key.

        :param key: A string key representing the new tile image to use.
        :param position: A tuple (x, y) representing the tile's position on the map.
        """
        image_mapping = {
            "building_in_progress": {"image_path": "../Graphics/Tiles/building_in_progress.png",
                                     "valid_interaction_types": [],
                                     "is_obstacle": True},
            "fishing_hole": {"image_path": "../Graphics/Tiles/fishing_hole.png",
                             "valid_interaction_types": [],
                             "is_obstacle": True},
            "ice_tile": {"image_path": "../Graphics/Tiles/ice_tile.png",
                         "valid_interaction_types": ["create_fishing_hole"],
                         "is_obstacle": False},
        }

        entry = image_mapping.get(key)
        if not entry:
            return
        image_path = entry.get("image_path")
        if not image_path:
            return
        valid_interaction_types = entry.get("valid_interaction_types")
        is_obstacle = entry.get("is_obstacle")

        new_image = pygame.image.load(image_path).convert()
        new_image = pygame.transform.scale(new_image, (self.TILESIZE, self.TILESIZE))

        tile = self.tile_map.get(position)

        if tile:
            groups = tile.groups()

            for group in groups:
                group.remove(tile)

            tile.image = new_image
            tile.valid_interaction_types = valid_interaction_types

            for group in groups:
                if group is self.obstacle_sprites:
                    continue
                group.add(tile)

            if is_obstacle:
                self.obstacle_sprites.add(tile)

            self.visible_sprites.update_tile_on_ground_surface(tile)

        
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
            props = getattr(object_, "properties", None) or {}
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

    def create_painted_ground_layer(self, tmx_object_layer):
        """
        Visual-only painted background chunks.

        Image objects on this layer are composited into the ground surface but are
        intentionally not registered as obstacles. Collision/effects stay authored
        by the normal TMX gameplay layers.
        """
        tiled_tile_width = self.tmxdata.tilewidth
        tiled_tile_height = self.tmxdata.tileheight
        width_scaling_factor = TILESIZE / tiled_tile_width
        height_scaling_factor = TILESIZE / tiled_tile_height

        for object_ in tmx_object_layer:
            image = getattr(object_, "image", None)
            if image is None:
                continue

            scaled_w = max(1, int(round(object_.width * width_scaling_factor)))
            scaled_h = max(1, int(round(object_.height * height_scaling_factor)))
            x_pos = (object_.x * TILESIZE) / tiled_tile_width
            y_pos = (object_.y * TILESIZE) / tiled_tile_height
            image = pygame.transform.scale(image, (scaled_w, scaled_h))
            Tile(
                (x_pos, y_pos),
                [self.ground_sprites],
                "ground",
                surface=image,
            )

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

    def _try_spawn_rts_object(
        self, object_, props, x_pos, y_pos, width_scaling_factor, height_scaling_factor
    ):
        # Legacy rts_node_kind objects on Object Layer 1 are superseded by dedicated TMX layers.
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

            props = getattr(object_, "properties", None) or {}

            if self._try_spawn_animated_env_object(
                object_, props, x_pos, y_pos, width_scaling_factor, height_scaling_factor
            ):
                continue

            if self._try_spawn_rts_object(
                object_, props, x_pos, y_pos, width_scaling_factor, height_scaling_factor
            ):
                continue

            interact_key = str(props.get("interactable_type", "")).strip().lower()
            prof_key = str(props.get("interactable_profile", "")).strip()
            if not prof_key and interact_key == "chest":
                prof_key = DEFAULT_CHEST_INTERACTABLE_PROFILE

            merged = None
            if prof_key:
                merged = self._merge_env_interactable_props(prof_key, props)
                if merged is None:
                    merged = self._merge_env_interactable_props(
                        DEFAULT_CHEST_INTERACTABLE_PROFILE, props
                    )

            if merged is not None:
                kind = str(merged.get("kind", "loot_container")).strip().lower()
                if kind == "loot_container":
                    gw = object_.width * width_scaling_factor
                    gh = object_.height * height_scaling_factor
                    if gw <= 0 or gh <= 0:
                        gw = TILESIZE
                        gh = TILESIZE
                    target_w = max(1, int(round(gw)))
                    target_h = max(1, int(round(gh)))
                    built = self._try_build_loot_chest_assets(
                        merged, (target_w, target_h)
                    )
                    if built is None:
                        continue
                    idle_surface, hit_frames, layout_meta = built
                    dx, dy = layout_meta.get("topleft_offset", (0, 0))
                    disp = layout_meta.get("display_size") or (
                        target_w,
                        target_h,
                    )
                    InteractableChest(
                        (x_pos + dx, y_pos + dy),
                        [self.obstacle_sprites, self.visible_sprites],
                        self.environment_interactables,
                        idle_surface,
                        hit_frames,
                        merged["loot_info"],
                        profile_id=merged.get("profile_id", ""),
                        kind=kind,
                        interaction_margin=merged.get("interaction_margin", 48),
                        open_animation_path=merged.get("open_animation_path"),
                        image_open_path=merged.get("image_open_path"),
                        merged_config=merged,
                        tmx_folder=getattr(self, "tmx_folder", None),
                        display_size=tuple(int(x) for x in disp),
                    )
                    continue
                if kind == "seat":
                    gw = object_.width * width_scaling_factor
                    gh = object_.height * height_scaling_factor
                    if gw <= 0 or gh <= 0:
                        gw = TILESIZE
                        gh = TILESIZE
                    target_w = max(1, int(round(gw)))
                    target_h = max(1, int(round(gh)))
                    built = self._try_build_seat_assets(
                        merged, (target_w, target_h)
                    )
                    if built is None:
                        continue
                    idle_surface, layout_meta = built
                    dx, dy = layout_meta.get("topleft_offset", (0, 0))
                    disp = layout_meta.get("display_size") or (
                        target_w,
                        target_h,
                    )
                    InteractableSeat(
                        (x_pos + dx, y_pos + dy),
                        [self.obstacle_sprites, self.visible_sprites],
                        self.environment_interactables,
                        idle_surface,
                        profile_id=merged.get("profile_id", ""),
                        kind=kind,
                        interaction_margin=merged.get("interaction_margin", 48),
                        merged_config=merged,
                        display_size=tuple(int(x) for x in disp),
                    )
                    continue
                if kind == "resource_node":
                    entity_type = str(
                        merged.get("entity_type") or props.get("rts_entity_type") or ""
                    ).strip()
                    if entity_type:
                        gw = object_.width * width_scaling_factor
                        gh = object_.height * height_scaling_factor
                        if gw <= 0:
                            gw = TILESIZE
                        if gh <= 0:
                            gh = TILESIZE
                        cfg = resource_node_config(entity_type)
                        node = ResourceNode(
                            (x_pos + gw / 2, y_pos + gh / 2),
                            [self.obstacle_sprites, self.visible_sprites],
                            cfg,
                            self.rts_registry,
                        )
                        self.environment_interactables.append(node)
                    continue
                if kind == "rts_building":
                    building_type = str(
                        merged.get("building_type")
                        or merged.get("entity_type")
                        or props.get("rts_entity_type")
                        or ""
                    ).strip()
                    if building_type:
                        cx = x_pos + TILESIZE / 2
                        cy = y_pos + TILESIZE / 2
                        gw = object_.width * width_scaling_factor
                        gh = object_.height * height_scaling_factor
                        if gw > 0 and gh > 0:
                            cx = x_pos + gw / 2
                            cy = y_pos + gh / 2
                        cfg = dropoff_config(building_type)
                        building = DropoffBuilding(
                            (cx, cy),
                            [self.obstacle_sprites, self.visible_sprites],
                            cfg,
                            self.rts_registry,
                        )
                        self.environment_interactables.append(building)
                    continue
                _tmx_layout_log.debug(
                    "env interactable kind=%r not implemented; using static Tile",
                    kind,
                )

            image = object_.image

            if image is not None:
                scaled_w = max(1, int(round(object_.width * width_scaling_factor)))
                scaled_h = max(1, int(round(object_.height * height_scaling_factor)))
                image = pygame.transform.scale(image, (scaled_w, scaled_h))
                mask = pygame.mask.from_surface(image)
                Tile(
                    (x_pos, y_pos),
                    [self.obstacle_sprites, self.ground_sprites],
                    "ground",
                    mask=mask,
                    surface=image,
                )
                continue

            shape_rect, shape_mask, draw_pts = self._mask_and_rect_for_tmx_shape(object_)
            if shape_mask is None:
                continue

            sam3_class = normalize_sam3_class(props.get("sam3_class"))
            collision_mode = collision_mode_for_props(props)
            if collision_mode == "canopy":
                self._spawn_canopy_shape_obstacle(
                    shape_rect, shape_mask, draw_pts, props, sam3_class
                )
            else:
                self._spawn_solid_shape_obstacle(
                    shape_rect, shape_mask, draw_pts, props, sam3_class
                )


    def _attach_sam3_metadata(self, tile, props):
        for key in ("sam3_class", "sam3_confidence", "chunk_id", "collision_mode"):
            if key in props:
                setattr(tile, key, props[key])

    def _spawn_solid_shape_obstacle(self, shape_rect, shape_mask, draw_pts, props, sam3_class):
        surface = obstacle_surface_for_shape(
            width=shape_rect.width,
            height=shape_rect.height,
            draw_pts=draw_pts,
            sam3_class=sam3_class,
            collision_mode="solid",
        )
        groups = [self.obstacle_sprites]
        if DEBUG_DRAW_OBSTACLE_TINT:
            groups.append(self.ground_sprites)
        shape_tile = Tile(
            (shape_rect.x, shape_rect.y),
            groups,
            "ground",
            mask=shape_mask,
            surface=surface,
        )
        self._attach_sam3_metadata(shape_tile, props)

    def _spawn_canopy_shape_obstacle(self, shape_rect, shape_mask, draw_pts, props, sam3_class):
        surf_w, surf_h = shape_rect.width, shape_rect.height
        trunk_mask, canopy_mask = split_trunk_canopy_masks(shape_mask, surf_w, surf_h)
        if trunk_mask.count():
            if DEBUG_DRAW_OBSTACLE_TINT:
                rgba = tint_rgba_for_class(sam3_class)
                rgba = (rgba[0], rgba[1], rgba[2], min(255, rgba[3] + 18))
                trunk_surface = trunk_mask.to_surface(
                    setcolor=rgba,
                    unsetcolor=(0, 0, 0, 0),
                )
            else:
                trunk_surface = pygame.Surface((surf_w, surf_h), pygame.SRCALPHA)
            groups = [self.obstacle_sprites]
            if DEBUG_DRAW_OBSTACLE_TINT:
                groups.append(self.ground_sprites)
            trunk_tile = Tile(
                (shape_rect.x, shape_rect.y),
                groups,
                "ground",
                mask=trunk_mask,
                surface=trunk_surface,
            )
            self._attach_sam3_metadata(trunk_tile, props)

        if canopy_mask.count():
            canopy_surface = canopy_mask.to_surface(
                setcolor=CANOPY_OVERHEAD_RGBA,
                unsetcolor=(0, 0, 0, 0),
            )
            self.overhead_areas.append((shape_rect.copy(), canopy_surface))
            if DEBUG_DRAW_OBSTACLE_TINT:
                debug_rgba = tint_rgba_for_class(sam3_class)
                debug_canopy = canopy_mask.to_surface(
                    setcolor=(debug_rgba[0], debug_rgba[1], debug_rgba[2], max(24, debug_rgba[3] - 24)),
                    unsetcolor=(0, 0, 0, 0),
                )
                Tile(
                    (shape_rect.x, shape_rect.y),
                    [self.ground_sprites],
                    "ground",
                    mask=None,
                    surface=debug_canopy,
                )
    
    
    
    
    def _mask_and_rect_for_tmx_shape(self, obj):
        """Build a collision/effect mask from a pytmx rect, ellipse, or polygon object."""
        tw = self.tmxdata.tilewidth
        th = self.tmxdata.tileheight
        sx = self.TILESIZE / tw
        sy = self.TILESIZE / th

        x_game = obj.x * sx
        y_game = obj.y * sy

        points = getattr(obj, "points", None)
        if points:
            scaled = [(float(px) * sx, float(py) * sy) for px, py in points]
            min_px = min(p[0] for p in scaled)
            max_px = max(p[0] for p in scaled)
            min_py = min(p[1] for p in scaled)
            max_py = max(p[1] for p in scaled)
            surf_w = max(1, int(math.ceil(max_px - min_px)))
            surf_h = max(1, int(math.ceil(max_py - min_py)))
            draw_pts = [(int(px - min_px), int(py - min_py)) for px, py in scaled]
            surf = pygame.Surface((surf_w, surf_h), pygame.SRCALPHA)
            pygame.draw.polygon(surf, (255, 255, 255, 255), draw_pts)
            rect = pygame.Rect(int(x_game), int(y_game), surf_w, surf_h)
            return rect, pygame.mask.from_surface(surf), draw_pts

        w_game = obj.width * sx
        h_game = obj.height * sy
        surf_w = max(1, int(round(w_game)))
        surf_h = max(1, int(round(h_game)))
        surf = pygame.Surface((surf_w, surf_h), pygame.SRCALPHA)
        if getattr(obj, "ellipse", False):
            pygame.draw.ellipse(surf, (255, 255, 255, 255), (0, 0, surf_w, surf_h))
            draw_pts = []
        else:
            draw_pts = [(0, 0), (surf_w, 0), (surf_w, surf_h), (0, surf_h)]
            pygame.draw.rect(surf, (255, 255, 255, 255), (0, 0, surf_w, surf_h))
        rect = pygame.Rect(int(x_game), int(y_game), surf_w, surf_h)
        return rect, pygame.mask.from_surface(surf), draw_pts

    def _make_effect_area_from_tiled_object(self, obj, layer_name, idx):
        """
        Convert a pytmx shape (rect/ellipse/polygon) into an EffectArea.
        This:
          • computes the game-space rect
          • draws the shape ONLY to generate a mask
          • stores rect + mask + properties + original tmx object
        """
        rect, mask, _draw_pts = self._mask_and_rect_for_tmx_shape(obj)
        surf_w, surf_h = rect.width, rect.height
        x_game, y_game = rect.x, rect.y
        tw = self.tmxdata.tilewidth
        th = self.tmxdata.tileheight
        sx = self.TILESIZE / tw
        sy = self.TILESIZE / th
        w_game = obj.width * sx
        h_game = obj.height * sy
    
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
            _tmx_layout_log.debug(
                "Registered TMX spawner object_id=%r layer=%r anchor=(%.2f, %.2f) rect_px=(%.1f, %.1f, %.1f, %.1f) "
                "enemy_keys=%s neutral_keys=%s frequency=%s spawn_limits=%s spawn_number=%s distance=%s",
                object_info.get("object_id"),
                layer_name,
                object_info.get("anchor_tx", 0.0),
                object_info.get("anchor_ty", 0.0),
                object_info.get("rect_x_px", 0.0),
                object_info.get("rect_y_px", 0.0),
                object_info.get("rect_w_px", 0.0),
                object_info.get("rect_h_px", 0.0),
                sorted((spawner_config.get("enemy_spawn_weights") or {}).keys()),
                sorted((spawner_config.get("neutral_spawn_weights") or {}).keys()),
                spawner_config.get("frequency"),
                spawner_config.get("spawn_limits"),
                spawner_config.get("spawn_number"),
                spawner_config.get("distance", 2000),
            )
            
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

    def _extract_weight_map(self, data, key, config_name):
        raw = data.get(key)
        if raw is None:
            return None
        if isinstance(raw, str):
            if not raw.strip():
                return None
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as e:
                _tmx_layout_log.debug(
                    "Could not parse %s %s as JSON: %s",
                    config_name,
                    key,
                    e,
                )
                return None
        if not isinstance(raw, dict):
            _tmx_layout_log.debug(
                "%s %s must be an object (dict)",
                config_name,
                key,
            )
            return None
        return raw if len(raw) > 0 else None

    def _extract_spawn_limits(self, data):
        raw = data.get("spawn_limits")
        if raw is None:
            return {}
        if isinstance(raw, str):
            if not raw.strip():
                return {}
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as e:
                _tmx_layout_log.debug("Could not parse spawner_config spawn_limits as JSON: %s", e)
                return {}
        if not isinstance(raw, dict):
            _tmx_layout_log.debug(
                "spawner_config spawn_limits must be an object (dict), got %s",
                type(raw).__name__,
            )
            return {}

        parsed = {}
        for key in ("general", "enemy", "neutral"):
            value = raw.get(key)
            if isinstance(value, int) and value >= 0:
                parsed[key] = value
            elif value is not None:
                _tmx_layout_log.debug(
                    "spawner_config spawn_limits.%s must be a non-negative int, got %r",
                    key,
                    value,
                )

        raw_types = raw.get("types")
        if raw_types is not None:
            if isinstance(raw_types, dict):
                parsed_types = {}
                for actor_type, cap in raw_types.items():
                    if isinstance(cap, int) and cap >= 0:
                        parsed_types[str(actor_type)] = cap
                    else:
                        _tmx_layout_log.debug(
                            "spawner_config spawn_limits.types[%r] must be a non-negative int, got %r",
                            actor_type,
                            cap,
                        )
                if parsed_types:
                    parsed["types"] = parsed_types
            else:
                _tmx_layout_log.debug(
                    "spawner_config spawn_limits.types must be an object (dict), got %s",
                    type(raw_types).__name__,
                )
        return parsed

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

        enemy_weights = self._extract_weight_map(data, "enemy_spawn_weights", "spawner_config")
        neutral_weights = self._extract_weight_map(data, "neutral_spawn_weights", "spawner_config")
        if enemy_weights is None and neutral_weights is None:
            _tmx_layout_log.debug(
                "spawner_config must include enemy_spawn_weights and/or neutral_spawn_weights"
            )
            return None

        legacy_spawn_limit = data.get("spawn_limit", 60)
        if not isinstance(legacy_spawn_limit, int) or legacy_spawn_limit < 0:
            _tmx_layout_log.debug(
                "spawner_config spawn_limit must be a non-negative int, got %r. Using default 60.",
                legacy_spawn_limit,
            )
            legacy_spawn_limit = 60
        spawn_limits = self._extract_spawn_limits(data)
        if "general" not in spawn_limits:
            spawn_limits["general"] = legacy_spawn_limit

        config = {
            "spawn_type": data.get("spawn_type", "random_weights"),
            "frequency": data.get("frequency", 10000),
            "spawn_limit": legacy_spawn_limit,
            "spawn_number": data.get("spawn_number", 1),
            "spawn_limits": spawn_limits,
        }
        if enemy_weights is not None:
            config["enemy_spawn_weights"] = enemy_weights
        if neutral_weights is not None:
            config["neutral_spawn_weights"] = neutral_weights
        for opt in ("distance", "time_scaled", "scale_type", "scale_max"):
            if opt in data:
                config[opt] = data[opt]

        if "spawn_team_id" in data:
            raw_spawn_team_id = data.get("spawn_team_id")
            if isinstance(raw_spawn_team_id, str):
                spawn_team_id = raw_spawn_team_id.strip()
                if spawn_team_id:
                    config["spawn_team_id"] = spawn_team_id
                else:
                    _tmx_layout_log.debug(
                        "spawner_config spawn_team_id must be a non-empty string when provided"
                    )
            else:
                _tmx_layout_log.debug(
                    "spawner_config spawn_team_id must be a string, got %s",
                    type(raw_spawn_team_id).__name__,
                )

        if "item_drop_info" in data:
            raw_drop = data["item_drop_info"]
            if isinstance(raw_drop, dict):
                config["item_drop_info"] = raw_drop
            else:
                _tmx_layout_log.debug(
                    "spawner_config item_drop_info must be an object, got %s",
                    type(raw_drop).__name__,
                )

        if "neutral_attributes" in data:
            raw_attrs = data["neutral_attributes"]
            if isinstance(raw_attrs, dict):
                config["neutral_attributes"] = raw_attrs
            else:
                _tmx_layout_log.debug(
                    "spawner_config neutral_attributes must be an object, got %s",
                    type(raw_attrs).__name__,
                )

        return config

    def _extract_entity_spawn_config(self, props):
        """
        Read a single Tiled property entity_spawn_config: JSON string (or dict) for one placed entity.
        Requires kind=enemy|neutral and type. For neutral, attributes defaults to {}.
        """
        raw = props.get("entity_spawn_config")
        if raw is None:
            _tmx_layout_log.debug("Placed entity object missing entity_spawn_config property")
            return None
        if isinstance(raw, str) and not str(raw).strip():
            _tmx_layout_log.debug("Placed entity entity_spawn_config is empty")
            return None

        if isinstance(raw, str):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                _tmx_layout_log.debug("Invalid entity_spawn_config JSON: %s", e)
                return None
        elif isinstance(raw, dict):
            data = dict(raw)
        else:
            _tmx_layout_log.debug(
                "entity_spawn_config must be string or dict, got %s",
                type(raw).__name__,
            )
            return None

        if not isinstance(data, dict):
            _tmx_layout_log.debug(
                "entity_spawn_config JSON must be an object at top level"
            )
            return None

        kind = str(data.get("kind", "")).strip().lower()
        if kind not in ("enemy", "neutral"):
            _tmx_layout_log.debug(
                "entity_spawn_config kind must be 'enemy' or 'neutral', got %r",
                data.get("kind"),
            )
            return None

        entity_type = data.get("type")
        if entity_type is None or (isinstance(entity_type, str) and not str(entity_type).strip()):
            _tmx_layout_log.debug(
                "entity_spawn_config must include non-empty type"
            )
            return None

        config = dict(data)
        config["kind"] = kind
        config["type"] = str(entity_type).strip()
        if kind == "neutral":
            attrs = config.get("attributes", {})
            if not isinstance(attrs, dict):
                _tmx_layout_log.debug(
                    "entity_spawn_config neutral attributes must be an object, got %s",
                    type(attrs).__name__,
                )
                return None
            config["attributes"] = attrs
        return config

    def create_placed_entity_layer(self, tmx_object_layer):
        """
        Object layer whose name contains 'placed_entities': each object needs entity_spawn_config.
        Spawns exactly one enemy or neutral from the object's position in tile-space.
        """
        if not hasattr(self, "spawner"):
            _tmx_layout_log.debug(
                "spawner not set; skipping placed entity layer %r",
                getattr(tmx_object_layer, "name", ""),
            )
            return
        if not hasattr(self, "placed_enemy_spawns"):
            self.placed_enemy_spawns = []
        tiled_tile_width = self.tmxdata.tilewidth
        tiled_tile_height = self.tmxdata.tileheight

        for obj in tmx_object_layer:
            props = dict(obj.properties) if hasattr(obj, "properties") else {}
            config = self._extract_entity_spawn_config(props)
            if not config:
                continue
            x_px, y_px, _gw, _gh = self._game_rect_for_tmx_object(
                obj, tiled_tile_width, tiled_tile_height
            )
            pos = (float(x_px) / float(TILESIZE), float(y_px) / float(TILESIZE))
            spawn_cfg = dict(config)
            spawn_cfg["pos"] = pos

            if spawn_cfg["kind"] == "enemy":
                # CS2 (server-authoritative co-op): record every placed-enemy
                # spawn config so a multiplayer client can upload the map's enemy
                # spec to the server, which owns the enemy sim. Collected
                # regardless of spawning (the spawner is suppressed in MP, so
                # spawn_enemy is a no-op there -- but the spec is still needed).
                self.placed_enemy_spawns.append(spawn_cfg)
                self.spawner.spawn_enemy(spawn_cfg)
            else:
                self.spawner.spawn_neutral(spawn_cfg)
    
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
            "object_id": getattr(obj, "id", None),
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
        # CS2: collected fresh each layout load -- the placed-enemy spawn spec a
        # multiplayer client uploads so the server can own the enemy sim.
        self.placed_enemy_spawns = []
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
        self.effect_cell_grid = None
        
        self.tmxdata = load_pygame( tmx_path + '/map.tmx' )
        self.tmx_folder = os.path.abspath(tmx_path) if tmx_path else ""
        self.environment_interactables = []
        self.rts_registry = RtsWorldRegistry()

        # Fresh procedural grass for this map (LayoutManager reuses one GrassManager).
        self.grass_manager.grass_tiles.clear()
        self._load_grass_profiles(tmx_path)
        self._load_env_interactable_profiles(tmx_path)
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
                
            

        deep_snow_cells = {}
        for layout in self.tmx_ground_layers:
            deep_snow_cells.update(self._process_tile_layer(layout))

        try:
            from rts.build.sites_from_tiles import register_build_sites_from_cells

            indexed = register_build_sites_from_cells(self, deep_snow_cells)
            if indexed:
                _tmx_layout_log.debug("Indexed %d RTS build sites from tile properties", indexed)
        except Exception as exc:
            _tmx_layout_log.debug("RTS build site indexing skipped: %s", exc)

        self.visible_sprites.set_grass_grid(self.grass_tile_grid)

        for layout in self.tmx_object_layers:
            layer_name = getattr(layout, "name", "")
            layer_name_lower = layer_name.lower()
            if "placed_entities" in layer_name_lower:
                self.create_placed_entity_layer(layout)
            elif "item" in layer_name_lower and layer_name not in LAYER_ROLES:
                self.create_item_object_layer(layout)
            else:
                role = resolve_layer_role(layer_name)
                dispatch_object_layer(self, layout, role)
            
        self.effect_cell_grid = EffectCellGrid.build(
            self.all_effect_areas,
            self.TILESIZE,
            self.csv_layout_width,
            self.csv_layout_height,
        )
        
        
        items = []
        for sprite in self.obstacle_sprites:
            items.append(self.register_obstacle_sprite(sprite, live=False))
            
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
        self.walk_grid_cache = WalkGridCache(
            self.obstacle_quad_tree,
            self.csv_layout_width,
            self.csv_layout_height,
        )
        self.walk_grid_cache.prewarm_rts_workers()

        
        
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
        
        
        
     