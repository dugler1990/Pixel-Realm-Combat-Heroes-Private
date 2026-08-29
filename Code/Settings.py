import os

import pygame

# This is for file (images specifically) importing (This line changes the directory to where the project is saved)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Game setup
WIDTH = 800#1680
HEIGHT = 400#950
# Window size as a fraction of the primary monitor (used by Main2 when not fullscreen).
WINDOW_WIDTH_RATIO = 0.6
WINDOW_HEIGHT_RATIO = 0.6
FPS = 30
RENDER_BACKEND = os.environ.get("RENDER_BACKEND", "gpu")  # "cpu" | "gpu" — override via env for profiling
DISPLAY_FLAGS = pygame.SRCALPHA
TILESIZE =150#150
# Ground is composited into ONE surface and uploaded as ONE GL texture, so the whole world has
# to fit inside GL_MAX_TEXTURE_SIZE. The 7x6 sunspine map needs 22473x12258 at full scale and
# fails with a glTexImage2D error; it only runs shrunk to 0.586, discarding two thirds of the
# art. Setting this cuts the ground into textures of at most this size instead, which removes
# the ceiling. 0 keeps the single-surface path, which is still the default.
GROUND_CHUNK_SIZE = 4096
# Fraction of window width and height (1–100) used for the grass subsurface; centered on the display.
GRASS_VIEWPORT_PERCENT = 100
# Grass wind mode (see YSortCameraGroup.custom_draw):
# - "legacy_tile"  — per-tile wind angle from sin(t + x/100) (tile-by-tile phase); slightly slower, more variation.
# - "shared_patch" — one shared sway angle for all visible grass (whole patch in sync); slightly faster, smoother.
GRASS_WIND_MODE = "shared_patch"
# Wind rotation quantization in degrees (GrassManager cache buckets). Lower = smoother motion, more unique tile variants.
# 1 degree with the current int(sin(...)*15) wind driver yields ~31 sway states (-15..15) for a high-but-safe smoothness test.
GRASS_ROTATION_BUCKET_DEGREES = 1
# Grass GPU renderer (Phase A proof). When True and RENDER_BACKEND == "gpu", grass blades
# render via the per-blade instanced shader path (rotation in the vertex shader) instead of
# the CPU bitmap tile-cache path. Toggle here to A/B the two; no effect in CPU backend.
GRASS_GPU_INSTANCED = True

# Weather / time-of-day (see Weather.py). Real seconds for a full 24h day-night cycle
# (also paces precipitation spells). Default climate used when a level doesn't specify one;
# must be a key in Weather.CLIMATES ("temperate" | "snowy_cold" | "clear" | "stormy").
DAY_LENGTH_SECONDS = 180
WEATHER_DEFAULT_CLIMATE = "temperate"

# Benchmark mode (off by default). Used for isolated moving-entity collision tests.
BENCHMARK_ENABLED = False
BENCHMARK_LAYOUT_DIR = "../levels/benchmark"
BENCHMARK_ENTITY_COUNT = 10
BENCHMARK_SEED = 1337
BENCHMARK_DETERMINISTIC_SPAWN = True
BENCHMARK_ENEMY_TYPE = "raccoon"
# Comma-separated type:count pairs; when set, overrides single-type spawns (pad/truncate to entity_count).
# Example with BENCHMARK_ENTITY_COUNT = 40: raccoon:30,ice_mage:10
BENCHMARK_ENEMY_MIX = ""
BENCHMARK_PLAYER_HEALTH_MULTIPLIER = 50.0
BENCHMARK_BROADPHASE_BACKEND = "quadtree"  # "quadtree" | "grid"
BENCHMARK_PUSHBACK_FLOOR_ENABLED = False
BENCHMARK_PUSHBACK_MIN_THRESHOLD = 0.5
BENCHMARK_PUSHBACK_CAP_ENABLED = False
BENCHMARK_PUSHBACK_MAX_CAP = 16.0
BENCHMARK_METRICS_ENABLED = True
BENCHMARK_METRICS_LOG_EVERY_SEC = 5.0
BENCHMARK_METRICS_CSV_PATH = "../logs/benchmark_metrics.csv"
# Grass / perf runs: use ~5s warmup so caches settle, then ~15s+ measure (set 0 for manual no auto-exit).
BENCHMARK_AUTO_RUN_SECONDS = 15.0
BENCHMARK_WARMUP_SECONDS = 5.0
BENCHMARK_SPAWN_MAX_RING = 3  # Keep benchmark entities near player center
BENCHMARK_GRASS_ENABLED = True
BENCHMARK_GRASS_WIND_MODE = GRASS_WIND_MODE
BENCHMARK_GRASS_VIEWPORT_PERCENT = GRASS_VIEWPORT_PERCENT
BENCHMARK_GRASS_DISTURBANCE_ENABLED = True
# Grass sway speed in grass benchmarks: passed to YSortCameraGroup.custom_draw as wind_intensity (advances t via dt*60*intensity).
# Non-daytime layouts used 0 before; keep this >0 so legacy_tile / shared_patch actually animate under PRCH_BENCHMARK_GRASS_ENABLED.
BENCHMARK_GRASS_SWAY_INTENSITY = 3.0
# Programmatic grass inside benchmark arena (when PRCH_BENCHMARK_GRASS_ENABLED).
# Blade IDs are alphabetical indices in Graphics/Grass — low indices tend to shorter blades, high to taller.
BENCHMARK_ARENA_GRASS_DENSITY = 72
BENCHMARK_ARENA_GRASS_OPTIONS = [0, 1, 2, 3, 8, 9, 10, 11]

# Normal gameplay moving-entity broadphase defaults.
ENTITY_BROADPHASE_BACKEND = "grid"  # "quadtree" | "grid"
ENTITY_BROADPHASE_GRID_CELL_SIZE = 450

# Debug settings
SHOW_DEBUG_OVERLAY = True  # FPS / memory overlay in Main2 (separate from GameSettings.debug_mode)
DEBUG_DRAW_MASKS = False  # Draw collision masks for all entities and objects
DEBUG_DRAW_OBSTACLE_TINT = True  # Semi-transparent class hue on SAM3 / shape obstacle tiles
DEBUG_DRAW_EFFECT_RECTS = False  # Draw effect collision rects in red
DEBUG_DRAW_FACTION_OUTLINES = False  # Seeds GameSettings.debug_faction_outlines; toggle also in settings (Ctrl+Shift+S)
SAM3_TREE_TRUNK_HEIGHT_RATIO = 0.18  # Bottom fraction of tree polygons that block movement (canopy above)
# When True, entity mask PNGs are written under Graphics/Masks (dev/asset pipeline only).
EXPORT_ENTITY_MASKS_TO_DISK = False
HITBOX_OFFSET = {
	"player": -26,
	"object": -40,
	"grass": -10,
	"invisible": 0,
        "ground":0
	}

# UI
BAR_HEIGHT = 20
HEALTH_BAR_WIDTH = 200
ENERGY_BAR_WIDTH = 140
ITEM_BOX_SIZE = 80
UI_FONT = "../Graphics/Font/Joystix.ttf"
UI_FONT_SIZE = 18

# General Colors
UI_BG_COLOR = "#222222"
UI_BORDER_COLOR = "#111111"
TEXT_COLOR = "#EEEEEE"

# UI Colors
HEALTH_COLOR = "Red"
ENERGY_COLOR = "Blue"
UI_BORDER_COLOR_ACTIVE = "Gold"

# Upgrade Menu
TEXT_COLOR_SELECTED = "#111111"
BAR_COLOR = "#EEEEEE"
BAR_COLOR_SELECTED = "#111111"
UPGRADE_BG_COLOR_SELECTED = "#EEEEEE"

# Weapons
weapon_data = {
        "unarmed": {"cooldown": 50, "damage": 5, "graphic": "../Graphics/Weapons/Unarmed/Full.png"}, 
	"sword": {"cooldown": 100, "damage": 15, "graphic": "../Graphics/Weapons/Sword/Full.png"},
	"lance": {"cooldown": 400, "damage": 30, "graphic": "../Graphics/Weapons/Lance/Full.png"},
	"axe": {"cooldown": 300, "damage": 20, "graphic": "../Graphics/Weapons/Axe/Full.png"},
	"rapier": {"cooldown": 50, "damage": 8, "graphic": "../Graphics/Weapons/Rapier/Full.png"},
	"sai": {"cooldown": 80, "damage": 10, "graphic": "../Graphics/Weapons/Sai/Full.png"}
    }

# Magic
magic_data = {
	"flame": {"strength": 5, "cost": 20, "graphic": "../Graphics/Particles/Flame/fire.png"},
	"heal": {"strength": 20, "cost": 10, "graphic": "../Graphics/Particles/Heal/heal.png"},
    "ice_ball":{ "strength":10, "cost":1,"graphic":"../Graphics/Particles/Ice_Ball_Down/ice_ball.png" }
	}

# Evasions / player abilities (type-dispatched via abilities.registry.build_ability)
DEFAULT_EVASION_LOADOUT = ["slide", "create_ice_clone"]

ability_data = {
    "slide": {
        "type": "dash",
        "cost": 20,
        "speed_mult": 3,
        "duration_ms": 300,
        "collision_mode": "pass_through",
        "presentation": {
            "status_template": "slide_{dir}",
            "particle_template": "slide_{dir}",
        },
    },
    "create_ice_clone": {
        "type": "instant",
        "cost": 2,
        "effect_type": "freeze",
        "radius": 5,
    },
    "leap_slam": {
        "type": "charged_leap_slam",
        "cost": 8,
        "min_hold_ms": 80,
        "max_hold_ms": 1500,
        "min_charge_ratio": 0.25,
        "max_horizontal_range": 1100,
        "min_arc_height": 64,
        "max_arc_height": 320,
        "arc_height": 64,
        "air_duration_min_ms": 280,
        "air_duration_max_ms": 650,
        "air_duration_ms": 650,
        "travel_ease_power": 2.0,
        "arc_rise_ratio": 0.55,
        "arc_hang_ratio": 0.18,
        "launch_snap_px": 16,
        "air_control_speed": 2.5,
        "air_control_max_ratio": 0.12,
        "min_impact_radius": 40,
        "max_impact_radius": 120,
        "base_damage": 25,
        "base_knockback": 14,
        "velocity_follow_through": 0.5,
        "damage_attack_type": "weapon",
        "air_collision_mode": "pass_through",
        "presentation": {
            "charge_status": "leap_windup_{dir}",
            "air_status": "jump_{dir}",
            "land_status": "land_{dir}",
            "end_status": "{dir}_idle",
            "particle_template": "leap_impact",
        },
    },
}

evasion_data = ability_data

# Enemies
monster_data = {
	"squid": {"health": 100,
               "exp": 180,
               "attack_type": "melee", 
               "attack_sound": "../Audio/Attack/Slash.wav", 
               "speed": 6, 
               "resistance": 3,
               "combat_config":{
                "melee_attacks": [{"damage": 8, "cooldown": 1500}],
               "melee_attack_radius": 80, 
               "notice_radius": 1000,
               
                'combat_context':{
                    'damage_player': True,
                    'trigger_death_particles': True,
                    'add_exp': True,
                    'update_quad_tree': True
                }
               }
               },
	"tribey_snake": {"health": 100,
               "exp": 180,
               "attack_type": "melee", 
               "attack_sound": "../Audio/Attack/Slash.wav", 
               "speed": 6, 
               "resistance": 3,
               "combat_config":{
                "melee_attacks": [{"damage": 8, "cooldown": 1500}],
               "melee_attack_radius": 80, 
               "notice_radius": 1000,
               
                'combat_context':{
                    'damage_player': True,
                    'trigger_death_particles': True,
                    'add_exp': True,
                    'update_quad_tree': True
                }
               }
               },
    
	"raccoon": {"health": 300, 
             "exp": 300,  
             "attack_type": "melee", 
             "attack_sound": "../Audio/Attack/Claw.wav", 
             "speed": 4, 
             "resistance": 3, 
             "combat_config":{
             "melee_attacks": [{"damage": 80, "cooldown": 1500}],
             "melee_attack_radius": 120, 
             "notice_radius": 1000,
             "special_attacks": [
                 {"name": "Dash",
                  "chance": 0.3,
                  "cooldown": 5000,
                  "cooldown_variability": 2000,
                  "speed_mult": 2.5,
                  "duration_ms": 350,
                  "collision_mode": "resolve",
                  "cost": 0,
                  "trigger_conditions": [{"name": "in_range_of_player",
                                          "parameters": {"radius": 200}}]},
             ],
                'combat_context':{
                    'damage_player': True,
                    'trigger_death_particles': True,
                    'add_exp': True,
                    'update_quad_tree': True
                }}
             },
	
    "spirit": {"health": 100,
               "exp": 200, 
               "attack_type": "melee", 
               "attack_sound": "../Audio/Attack/Fireball.wav", 
               "speed": 12, 
               "resistance": 3,
               "combat_config":{
                "melee_attacks": [{"damage": 9, "cooldown": 1000}],
               "melee_attack_radius": 60, 
               "notice_radius": 1000,
                   
                'combat_context':{
                    'damage_player': True,
                    'trigger_death_particles': True,
                    'add_exp': True,
                    'update_quad_tree': True
                }
               }
             },
               
	"bamboo": {"health": 70,
                "exp": 150, 
                "attack_type": "melee", 
                "attack_sound": "../Audio/Attack/Slash.wav", 
                "speed": 6,
                "resistance": 3,
                "combat_config":{
                "melee_attacks": [{"damage": 6, "cooldown": 1000}],
                "melee_attack_radius": 50, 
                "notice_radius": 1000,
                
                'combat_context':{
                    'damage_player': True,
                    'trigger_death_particles': True,
                    'add_exp': True,
                    'update_quad_tree': True
                }
                }
            },
    # TODO: i was previously using the attack type for attack animations, 
    #       now the attack_type defines the combatstrategy subclass.
    #       the animations with attacks are setup so we should take advantage of this at some point.
    
    "ice_ghost": {
        "health": 70,
        "exp": 150,
        "attack_type": "melee",
        "attack_sound": "../Audio/Attack/Slash.wav",
        "speed": 9,
        "resistance": 3,
        "combat_config":{
        "melee_attack_radius": 50,
        "notice_radius": 2500,
        "melee_attacks": [{"damage": 20, "cooldown": 1000}],
        "ranged_attacks": [],
        "melee_parry_chance": 0.0,
        "projectile_parry_chance": 0.0,
        "parry_cooldown": 0,
        
            'combat_context':{
                'damage_player': True,
                'trigger_death_particles': True,
                'add_exp': True,
                'update_quad_tree': True
                }
        }
        },
        "tribey_spear": {
            "health": 70,
            "exp": 150,
            "attack_type": "melee",
            "attack_sound": "../Audio/Attack/Slash.wav",
            "speed": 15,
            "resistance": 3,
            "combat_config":{
            "melee_attack_radius": 50,
            "notice_radius": 2500,
            "melee_attacks": [{"damage": 6, "cooldown": 1000}],
            "ranged_attacks": [],
            "melee_parry_chance": 0.0,
            "projectile_parry_chance": 0.0,
            "parry_cooldown": 0,
            
                'combat_context':{
                    'damage_player': True,
                    'trigger_death_particles': True,
                    'add_exp': True,
                    'update_quad_tree': True
                    }
            }
        },
        "demon_dog": {
            "health": 50,
            "exp": 200,
            "attack_type": "ranged",
            "attack_sound": "../Audio/Attack/Slash.wav",
            "speed": 7,
            "resistance": 3,
            "combat_config":{
            "melee_attack_radius":0,  # TODO: just to not error out, i actually need to refine this, if he doesnt have melee attack of parry possibility, he should not have radius, 
                                      # infact, each parry, like each attack should have its own radius, 
                                      # i need to create new classes.
            "ranged_attack_radius": 350,
            "notice_radius": 1000,
            "melee_attacks": [],
            "ranged_attacks": [{"type": "demon_dog_projectile", "damage": 15, "cooldown": 1500}],
            "melee_parry_chance": 0.0,
            "projectile_parry_chance": 0.0,
            "parry_cooldown": 0,
            
            'combat_context':{
                'damage_player': True,
                'fire_projectile': True,
                'trigger_death_particles': True,
                'add_exp': True,
                'update_quad_tree': True
                }
            }
        },
        "venom_plant": {
            "health": 500,
            "exp": 200,
            "attack_type": "ranged",
            "attack_sound": "../Audio/Attack/Slash.wav",
            "speed": 1,
            "resistance": 3,
            "combat_config":{
            "melee_attack_radius":0,  # TODO: just to not error out, i actually need to refine this, if he doesnt have melee attack of parry possibility, he should not have radius, 
                                      # infact, each parry, like each attack should have its own radius, 
                                      # i need to create new classes.
            "ranged_attack_radius": 350,
            "notice_radius": 1000,
            "melee_attacks": [],
            "ranged_attacks": [{"type": "demon_dog_projectile", "damage": 15, "cooldown": 1500}],
            "melee_parry_chance": 0.0,
            "projectile_parry_chance": 0.0,
            "parry_cooldown": 0,
            
            'combat_context':{
                'damage_player': True,
                'fire_projectile': True,
                'trigger_death_particles': True,
                'add_exp': True,
                'update_quad_tree': True
                }
            }
        },
        "ice_mage": {
            "health": 4000,
            "exp": 200,
            "attack_type": "mixed",
            "attack_sound": "../Audio/Attack/Slash.wav",
            "speed": 7,
            "resistance": 3,
            "combat_config": {
                "special_attacks":[{"name":"Teleport",
                                    "chance":float(0.01),
                                    "cooldown":10000,
                                    "cooldown_variability":10000,
                                    "max_distance":390,
                                    "trigger_conditions":[{"name":"in_range_of_player",
                                                           "parameters":{"radius":100}}]},
                                   {"name":"MultiShotIceball",
                                                       "chance":float(0.1),
                                                       "cooldown":10000,
                                                       "cooldown_variability":10000,
                                                       "num_shots":10,
                                                       "projectile_type":"demon_dog_projectile",
                                                       "trigger_conditions":[{"name":"in_range_of_player",
                                                                              "parameters":{"radius":500}}]},
                                   
                                   
                                   {"name":"SummonIceGhosts",
                                                       "chance":float(0.1),
                                                       "cooldown":5000,
                                                       "cooldown_variability":1000,
                                                       "cast_time":2000,
                                                       "damage_threshold": 200,
                                                       "spawn_radius": 400,
                                                       "trigger_conditions":[{"name":"in_range_of_player",
                                                                              "parameters":{"radius":500}}]}],
                "melee_notice_radius": 200,
                "melee_attack_radius": 50,
                "ranged_attack_radius": 400,
                "notice_radius": 10000,
                "melee_attacks": [{"damage": 15, "cooldown": 700}],
                "ranged_attacks": [{"type": "demon_dog_projectile", "damage": 15, "cooldown": 1500}],
                "melee_parry_chance": 0.5,
                "projectile_parry_chance": 0.5,
                "parry_cooldown": 1000,
                'evasive_change_interval': 500,
                'combat_context':{
                'damage_player': True,
                'fire_projectile': True,
                'redirect_projectile': True,
                'trigger_death_particles': True,
                'add_exp': True,
                'spawn_enemy': True,
                'update_quad_tree': True
                }
            }
        },

	"eskimo_worker": {
		"health": 50,
		"exp": 0,
		"attack_type": "melee",
		"attack_sound": "../Audio/Attack/Claw.wav",
		"speed": 4,
		"resistance": 3,
		"combat_config": {
			"melee_attacks": [{"damage": 6, "cooldown": 1000}],
			"melee_attack_radius": 80,
			"notice_radius": 1000,
			"entity_collision_push_static": 15,
			"entity_collision_push_moving": 3.0,
			"use_mask_entity_collision_normal": True,
			"use_mask_obstacle_collision_normal": True,
			"mask_collision_min_deflect_deg": 30,
			"combat_context": {},
		},
	},
	"jungle_worker": {
		"health": 50,
		"exp": 0,
		"attack_type": "melee",
		"attack_sound": "../Audio/Attack/Slash.wav",
		"speed": 4,
		"resistance": 3,
		"combat_config": {
			"melee_attacks": [{"damage": 6, "cooldown": 1000}],
			"melee_attack_radius": 80,
			"notice_radius": 1000,
			"combat_context": {},
		},
	},
	"eskimo_chief": {
		"health": 200,
		"exp": 0,
		"attack_type": "melee",
		"attack_sound": "../Audio/Attack/Claw.wav",
		"speed": 3,
		"resistance": 3,
		"combat_config": {
			"melee_attacks": [{"damage": 10, "cooldown": 1200}],
			"melee_attack_radius": 80,
			"notice_radius": 1000,
			"combat_context": {},
		},
	},
	"jungle_chief": {
		"health": 200,
		"exp": 0,
		"attack_type": "melee",
		"attack_sound": "../Audio/Attack/Slash.wav",
		"speed": 3,
		"resistance": 3,
		"combat_config": {
			"melee_attacks": [{"damage": 10, "cooldown": 1200}],
			"melee_attack_radius": 80,
			"notice_radius": 1000,
			"combat_context": {},
		},
	},
	
    }
