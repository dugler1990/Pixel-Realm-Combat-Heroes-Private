import os

# This is for file (images specifically) importing (This line changes the directory to where the project is saved)
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Game setup
WIDTH = 800#1680
HEIGHT = 400#950
# Window size as a fraction of the primary monitor (used by Main2 when not fullscreen).
WINDOW_WIDTH_RATIO = 0.6
WINDOW_HEIGHT_RATIO = 0.6
FPS = 30
TILESIZE = 150
# Fraction of window width and height (1–100) used for the grass subsurface; centered on the display.
GRASS_VIEWPORT_PERCENT = 100
# Grass wind mode (see YSortCameraGroup.custom_draw):
# - "legacy_tile"  — per-tile wind angle from sin(t + x/100) (tile-by-tile phase); slightly slower, more variation.
# - "shared_patch" — one shared sway angle for all visible grass (whole patch in sync); slightly faster, smoother.
GRASS_WIND_MODE = "shared_patch"
# Wind rotation quantization in degrees (GrassManager cache buckets). Lower = smoother motion, more unique tile variants.
GRASS_ROTATION_BUCKET_DEGREES = 1

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
BENCHMARK_GRASS_ENABLED = False
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
# Grass force clustering (benchmark + grass enabled only): beyond player_radius, only one blade per subcell group runs force math; followers copy leader rotation.
BENCHMARK_GRASS_CLUSTER_FORCES_ENABLED = False
BENCHMARK_GRASS_CLUSTER_PLAYER_RADIUS_PX = 280.0
BENCHMARK_GRASS_CLUSTER_SUBCELL_PX = 40
BENCHMARK_GRASS_CLUSTER_GROUP_SIZE = 3
BENCHMARK_GRASS_CLUSTER_JITTER_DEG = 0.0
# Mixed into deterministic follower jitter; defaults to BENCHMARK_SEED for reproducible A/B runs.
BENCHMARK_GRASS_CLUSTER_JITTER_SEED = BENCHMARK_SEED

# Normal gameplay moving-entity broadphase defaults.
ENTITY_BROADPHASE_BACKEND = "grid"  # "quadtree" | "grid"
ENTITY_BROADPHASE_GRID_CELL_SIZE = 450

# Debug settings
DEBUG_DRAW_MASKS = True  # Draw collision masks for all entities and objects
DEBUG_DRAW_EFFECT_RECTS = True  # Draw effect collision rects in red
DEBUG_DRAW_FACTION_OUTLINES = False  # Seeds GameSettings.debug_faction_outlines; toggle also in settings (Ctrl+Shift+S)
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
WATER_COLOR = "#71ddee"
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
               "notice_radius": 360,
               
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
               "notice_radius": 360,
               
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
             "notice_radius": 400,
             
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
               "notice_radius": 350,
                   
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
                "notice_radius": 300,
                
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
            "notice_radius": 400,
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
            "notice_radius": 400,
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
                "notice_radius": 600,
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
			"melee_attacks": [],
			"melee_attack_radius": 80,
			"notice_radius": 360,
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
			"melee_attacks": [],
			"melee_attack_radius": 80,
			"notice_radius": 360,
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
			"melee_attacks": [],
			"melee_attack_radius": 80,
			"notice_radius": 360,
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
			"melee_attacks": [],
			"melee_attack_radius": 80,
			"notice_radius": 360,
			"combat_context": {},
		},
	},
	
    }
