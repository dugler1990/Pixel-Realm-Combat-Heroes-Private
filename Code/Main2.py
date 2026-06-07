import pygame, sys
import os
import json

import game_logging
from game_logging import get_debug_logger

game_logging.setup_debug_logging()

_game_flow_log = get_debug_logger("game_flow")

from Settings import *
from Level4_tmxdev import Level4
from StartMenu import StartMenu
from PlayerSelection import PlayerSelection, unlocked_player_base_stats, unlocked_player_directory
from inputManager import InputManager
from LevelSelection import LevelSelection
from PlayerConfiguration import PlayerConfiguration
from game_settings import GameSettings
from SettingsMenu import SettingsMenu
from DeathMenu import DeathMenu
from benchmark_runtime import BENCHMARK_RUNTIME
from rts_validation_runtime import RTS_VALIDATION_RUNTIME
from render_backend import create_backend
import psutil

level_8_layout_path = '../levels/Map8'
level_7_layout_path = '../levels/Map7'
level_6_layout_path = '../levels/tmx'

LAYOUT_TO_LEVEL = {
    level_6_layout_path: 6,
    level_7_layout_path: 7,
    level_8_layout_path: 8,
}

DEV_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.dev_reload_state.json')

class Game:
    def __init__(self):
        pygame.init()
        desktop_sizes = pygame.display.get_desktop_sizes()
        if desktop_sizes:
            dw, dh = desktop_sizes[0]
        else:
            dw, dh = WIDTH, HEIGHT
        w = max(1, int(dw * WINDOW_WIDTH_RATIO))
        h = max(1, int(dh * WINDOW_HEIGHT_RATIO))
        self.backend = create_backend(w, h)
        self.screen = self.backend.raw_surface
        self.WIDTH = w
        self.HEIGHT = h

        self.clock = pygame.time.Clock()
        self.debug_info_surfaces = {} 


        self.input_manager = InputManager()
        self.level = None
        self.settings = GameSettings()
        self.settings_menu = SettingsMenu(self.settings)
        self.start_menu = StartMenu(self, self.input_manager)
        self.player_selection = PlayerSelection(self, self.input_manager)
        self.in_start_menu = True
        self.in_player_selection = False        
        self.state = "start_menu"  # Managing game states using a state variable
        pygame.mixer.set_num_channels(max(16, pygame.mixer.get_num_channels()))
        pygame.mixer.set_reserved(1)
        self.music_channel = pygame.mixer.Channel(0)
        self.main_music = pygame.mixer.Sound("../Audio/Main.ogg")
        self.music_channel.play(self.main_music, loops=-1)
        self.level_selection = LevelSelection(self, self.input_manager)
        self.death_menu = DeathMenu(self, self.input_manager)
        #self.player_configuration = PlayerConfiguration(self, self.input_manager)    
        self.in_level_selection = False  # New state for level selection
        self.current_level_number = None
        self.show_debug_info = SHOW_DEBUG_OVERLAY

        # Debug info update variables
        self.last_debug_update = 0
        self.debug_update_interval = 3000  # Update debug info every 500 milliseconds (0.5 seconds)

                # Initialize debug info variables
        self.debug_fps = 0
        self.debug_frame_time = 0
        self.debug_memory_usage = 0
        self.debug_cpu_usage = 0
        self.debug_sprite_count = 0
        self.debug_event_queue_length = 0        

        if RTS_VALIDATION_RUNTIME.enabled:
            self._bootstrap_rts_validation_run()
        elif BENCHMARK_RUNTIME.enabled:
            self._bootstrap_benchmark_run()

    def _bootstrap_rts_validation_run(self):
        if not unlocked_player_directory:
            raise RuntimeError("RTS validation requires at least one selectable player.")
        self.player_selection.selected_player_info_dir = unlocked_player_directory[0]
        base = unlocked_player_base_stats[0].copy()
        self.player_configuration = PlayerConfiguration(
            input_manager=self.input_manager,
            base_stats=base,
            remaining_points=0,
            game=self,
        )
        self.player_configuration.final_stats = base.copy()
        self.in_start_menu = False
        self.in_player_selection = False
        self.in_level_selection = False
        self.start_level(6)

    def _bootstrap_benchmark_run(self):
        if not unlocked_player_directory:
            raise RuntimeError("Benchmark mode requires at least one selectable player.")
        self.player_selection.selected_player_info_dir = unlocked_player_directory[0]
        base = unlocked_player_base_stats[0].copy()
        self.player_configuration = PlayerConfiguration(
            input_manager=self.input_manager,
            base_stats=base,
            remaining_points=0,
            game=self,
        )
        self.player_configuration.final_stats = base.copy()
        self.in_start_menu = False
        self.in_player_selection = False
        self.in_level_selection = False
        self.start_level(6)

    def _handle_global_shortcuts(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_s:
                mods = pygame.key.get_mods()
                if (mods & pygame.KMOD_CTRL) and (mods & pygame.KMOD_SHIFT):
                    self.settings_menu.toggle()
                    break

    def apply_settings(self):
        music_volume = self.settings.music_volume / 100.0
        sfx_volume = self.settings.sfx_volume / 100.0
        self.music_channel.set_volume(music_volume)
        for channel_idx in range(1, pygame.mixer.get_num_channels()):
            pygame.mixer.Channel(channel_idx).set_volume(sfx_volume)

        if self.level and hasattr(self.level, "weather") and self.level.weather:
            self.level.weather.time_speed_multiplier = self.settings.environment_speed

        if self.level and hasattr(self.level, "layout_manager") and self.level.layout_manager:
            visible = self.level.layout_manager.visible_sprites
            visible.runtime_debug_effect_rects = self.settings.debug_mode
            visible.runtime_debug_player_highlight = self.settings.debug_mode
            visible.runtime_debug_faction_outlines = self.settings.debug_faction_outlines



    def start_level(self, level_number, dev_restore=None):
        if dev_restore:
            player_info_dir = dev_restore['player_info_dir']
            player_stats = dev_restore['player_stats']
            layouts_dir = dev_restore['layouts_dir']
            player_position = dev_restore['player_position']
        else:
            player_info_dir = self.player_selection.selected_player_info_dir
            player_stats = self.player_configuration.final_stats
            if BENCHMARK_RUNTIME.enabled:
                layouts_dir = BENCHMARK_RUNTIME.layout_dir
            else:
                layouts_dir = (level_6_layout_path if level_number == 6 else
                              level_7_layout_path if level_number == 7 else level_8_layout_path)
            player_position = None

        if player_info_dir is not None:
            self.level = Level4(
                self.input_manager,
                player_info_dir,
                layouts_dir,
                player_stats,
                level_number=level_number,
                game_settings=self.settings,
                backend=self.backend,
            )
            if dev_restore and player_position is not None:
                self.level.player.rect.topleft = tuple(player_position)
                self.level.player.hitbox.topleft = tuple(player_position)
                self.level.player.update(
                    layout_switch=False,
                    QuadTree=self.level.layout_manager.obstacle_quad_tree,
                    entity_quad_tree=self.level.layout_manager.entity_quad_tree
                )
            self.current_level_number = level_number
            self.set_state("level")

    def set_state(self, new_state):
        """Central game state transitions (enter hooks)."""
        self.state = new_state
        if new_state == "death_menu":
            self.death_menu.reset_selection()

    def _dispatch_state(self, dt):
        handler = getattr(self, f"_state_{self.state}", None)
        if callable(handler):
            handler(dt)

    def _state_start_menu(self, dt):
        self.start_menu.handle_events()
        self.start_menu.draw()
        if not self.in_start_menu:
            self.set_state("player_selection")
            self.in_player_selection = True

    def _state_player_selection(self, dt):
        self.player_selection.handle_events()
        self.player_selection.draw()
        if not self.in_player_selection:
            self.set_state("player_configuration")
            selected_player_base_stats = self.player_selection.base_stats
            _game_flow_log.debug("BASE STATS: ")
            _game_flow_log.debug("%s", selected_player_base_stats)
            self.player_configuration = PlayerConfiguration(
                input_manager=self.input_manager,
                base_stats=selected_player_base_stats,
                remaining_points=10,
                game=self,
            )

    def _state_player_configuration(self, dt):
        self.player_configuration.handle_events()
        self.player_configuration.draw()
        _game_flow_log.debug(
            "in main finished indicattor: %s", self.player_configuration.finished
        )
        if self.player_configuration.finished:
            self.set_state("level_selection")
            self.in_level_selection = True

    def _state_level_selection(self, dt):
        self.level_selection.handle_events()
        self.level_selection.draw()
        if not self.in_level_selection:
            self.start_level(self.level_selection.selected_level)

    def _state_level(self, dt):
        self.level.run(dt)
        if getattr(self.level, "player_dead", False):
            self.set_state("death_menu")

    def _state_death_menu(self, dt):
        self.death_menu.draw()
        action = self.death_menu.handle_events()
        if action == "restart":
            if self.current_level_number is not None:
                self.start_level(self.current_level_number)
        elif action == "main_menu":
            self.level = None
            self.in_start_menu = True
            self.in_player_selection = False
            self.in_level_selection = False
            self.start_menu.selected_option = 0
            self.level_selection.selected_level = None
            self.set_state("start_menu")
        elif action == "exit":
            pygame.quit()
            sys.exit()

    #@profile
    def run(self):
        # Dev mode: restore from F5 hot reload state if present
        if os.path.exists(DEV_STATE_PATH):
            try:
                with open(DEV_STATE_PATH, 'r') as f:
                    dev_state = json.load(f)
                os.remove(DEV_STATE_PATH)
                self.start_level(dev_state['level_number'], dev_restore=dev_state)
            except (json.JSONDecodeError, KeyError) as e:
                _game_flow_log.debug("Dev reload state invalid, ignoring: %s", e)
                if os.path.exists(DEV_STATE_PATH):
                    os.remove(DEV_STATE_PATH)

        dt = 1.0 / FPS  # Initial dt for first frame (e.g. when restoring from dev reload)
        while True:
           # print(f" state in main : {self.state}")
            events = pygame.event.get()
            self._handle_global_shortcuts(events)
            self.input_manager.update(events)

            for event in events:
                if event.type == pygame.QUIT:
                    exit_code = 0
                    if RTS_VALIDATION_RUNTIME.shutdown_requested:
                        exit_code = RTS_VALIDATION_RUNTIME.shutdown_exit_code
                    pygame.quit()
                    sys.exit(exit_code)

            if self.settings_menu.visible:
                self.settings_menu.handle_events(events)

            self.apply_settings()

            if self.settings_menu.visible:
                # Pause normal state handlers while settings menu is active.
                if self.state == "level" and self.level and hasattr(self.level, "display_surface"):
                    self.level.display_surface.fill((0, 0, 0))
                    rts_session = getattr(self.level, "rts_session", None)
                    camera_focus = (
                        rts_session.camera_focus()
                        if rts_session is not None and rts_session.is_active()
                        else self.level.player
                    )
                    self.level.layout_manager.visible_sprites.custom_draw(
                        self.level.player, dt, 0, 0.5, camera_focus=camera_focus
                    )
                elif self.state == "death_menu":
                    self.death_menu.draw()
            else:
                self._dispatch_state(dt)

            if self.show_debug_info:
                self.update_debug_info()
                self.display_debug_info()

            self.settings_menu.draw(self.screen)

            pygame.display.update()
            dt = self.clock.tick(self.settings.fps_cap) /1000


    def update_debug_info(self):
        """Update the debug information."""
        current_time = pygame.time.get_ticks()
        if current_time - self.last_debug_update > self.debug_update_interval:
            self.last_debug_update = current_time

            # Update debug information
            self.debug_fps = self.clock.get_fps()
            self.debug_frame_time = self.clock.get_time()
            self.debug_memory_usage = psutil.Process(os.getpid()).memory_info().rss / 1024 ** 2
            self.debug_cpu_usage = psutil.cpu_percent()
            if self.level:
                self.debug_sprite_count = len(self.level.layout_manager.visible_sprites)
            self.debug_event_queue_length = len(pygame.event.get())


    def display_debug_info(self):
        """Display the debug information on the screen, using cached text surfaces."""
        font = pygame.font.Font(None, 30)
        text_spacing = 30
        current_y = self.HEIGHT - 30

        # List of debug info keys and their corresponding values
        debug_info = [
            ("FPS", f"FPS: {int(self.debug_fps)}"),
            ("Frame Time", f"Frame Time: {self.debug_frame_time}ms"),
            ("Memory", f"Memory: {self.debug_memory_usage:.2f}MB"),
            ("CPU Usage", f"CPU Usage: {self.debug_cpu_usage}%"),
            ("Visible Sprites", f"Visible Sprites: {self.debug_sprite_count}"),
            ("Event Queue", f"Event Queue: {self.debug_event_queue_length}")
        ]

        for key, value in debug_info:
            # Check if the surface needs to be updated
            if key not in self.debug_info_surfaces or self.debug_info_surfaces[key]['value'] != value:
                # Render new text surface and cache it
                text_surface = font.render(value, True, pygame.Color('white'))
                self.debug_info_surfaces[key] = {'surface': text_surface, 'value': value}

            # Blit the cached text surface
            self.backend.blit(self.debug_info_surfaces[key]['surface'], (10, current_y))
            current_y -= text_spacing


if  __name__ == "__main__":
    game = Game()
    game.run()
