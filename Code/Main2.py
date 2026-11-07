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
from PlayerSelection import (PlayerSelection, unlocked_player_base_stats, unlocked_player_directory,
                             unlocked_player_display_names, unlocked_player_names)
from inputManager import InputManager
from LevelSelection import LevelSelection
from PlayerConfiguration import PlayerConfiguration
from game_settings import GameSettings
from SettingsMenu import SettingsMenu
from DeathMenu import DeathMenu
from benchmark_runtime import BENCHMARK_RUNTIME
from rts_validation_runtime import RTS_VALIDATION_RUNTIME
from multiplayer_runtime import MULTIPLAYER_RUNTIME, default_spawn_offset
from network import MultiplayerClient
from level_layouts import DEFAULT_LAYOUT, LEVEL_TO_LAYOUT, MP_LEVEL_NUMBER
from render_backend import create_backend
from online import nakama
from online.lobby_ops import OP_CHAT, OP_NOTICE, OP_SET_CHARACTER, OP_SET_READY, OP_START, OP_STATE, OP_TICKET
from online.nakama import NakamaError
from online_menus import CreateScreen, FindScreen, LobbyScreen, SignInScreen
import legion_ui
from legion_ui import Gate, Grow
import psutil


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
        self.WIDTH = w
        self.HEIGHT = h
        # The painted gate: leaving the start menu, and after death (legion_ui.Gate).
        self.gate = Gate(self.backend)
        self.grow = None  # the chosen level's card growing into it (legion_ui.Grow)

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
        self.multiplayer_pending = False  # set by the "Local co-op (dev)" menu entry
        # Online play (Play online): the Nakama session, the lobby websocket, and the
        # four screens. The network calls live here; the screens are pure UI.
        self.online = None
        self.lobby_socket = None
        self.lobby_match_id = None
        self.online_character = unlocked_player_directory[0] if unlocked_player_directory else None
        self.signin_screen = SignInScreen()
        self.find_screen = FindScreen()
        self.create_screen = CreateScreen()
        self.lobby_screen = LobbyScreen([
            (path, name.replace("_", " "))
            for path, name in zip(unlocked_player_directory, unlocked_player_names)
        ])
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
        self.debug_blit_stats = None

        if RTS_VALIDATION_RUNTIME.enabled:
            self._bootstrap_rts_validation_run()
        elif BENCHMARK_RUNTIME.enabled:
            self._bootstrap_benchmark_run()
        elif MULTIPLAYER_RUNTIME.enabled:
            self._bootstrap_multiplayer_run()

    def _bootstrap_rts_validation_run(self):
        if not unlocked_player_directory:
            raise RuntimeError("RTS validation requires at least one selectable player.")
        idx = 0
        for i, path in enumerate(unlocked_player_directory):
            if str(path).rstrip("/").endswith("barb"):
                idx = i
                break
        self.player_selection.selected_player_info_dir = unlocked_player_directory[idx]
        base = unlocked_player_base_stats[idx].copy()
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

    def _bootstrap_multiplayer_run(self):
        # Env-var launch path (PRCH_MULTIPLAYER_ENABLED=1): character/player_id
        # come from MULTIPLAYER_RUNTIME. The "Local co-op (dev)" menu entry uses
        # the same _start_multiplayer_session with a menu-picked character.
        if not unlocked_player_directory:
            raise RuntimeError("Multiplayer requires at least one selectable player.")
        self._start_multiplayer_session(MULTIPLAYER_RUNTIME.character, MULTIPLAYER_RUNTIME.player_id)

    def _start_multiplayer_session(self, character_dir, player_id, host=None, port=None,
                                   level_number=MP_LEVEL_NUMBER, ticket=None):
        """Build a zero-point config for `character_dir`, load the co-op level, and
        connect+join the server as `player_id`. Shared by the env-var bootstrap, the
        Local co-op (dev) entry and online play, so the connect logic lives in one place.

        Online play passes the match server's host/port, its map, and the signed ticket
        from the lobby; the dev paths use MULTIPLAYER_RUNTIME's host/port and no ticket."""
        if character_dir in unlocked_player_directory:
            character_index = unlocked_player_directory.index(character_dir)
        else:
            character_index = 0
            character_dir = unlocked_player_directory[0]
        self.player_selection.selected_player_info_dir = character_dir
        base = unlocked_player_base_stats[character_index].copy()
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
        self.multiplayer_pending = False
        self.start_level(level_number)

        # Apply the per-player spawn offset to the ACTUAL local player, not just
        # the position we report. Every client bootstraps to the same fixed
        # spawn, so without this two clients overlap; offsetting only the
        # reported position (an earlier bug) baked in a constant error between
        # where a player really is and where remotes saw them. Offset is <1 tile
        # (TILESIZE=150), so it stays on the open spawn area.
        player = self.level.player
        if ticket is not None:
            spawn_x, spawn_y = default_spawn_offset(player_id)
        else:
            spawn_x, spawn_y = MULTIPLAYER_RUNTIME.spawn_x, MULTIPLAYER_RUNTIME.spawn_y
        if spawn_x or spawn_y:
            player.rect.centerx += int(spawn_x)
            player.rect.centery += int(spawn_y)
            player.hitbox.center = player.rect.center

        # The hitbox centre, the same point every later report uses.
        join_x, join_y = player.hitbox.centerx, player.hitbox.centery

        # The server loads its own map + runs the real Level4 and checks each report
        # against its walls with the same code this client moves with: it only needs
        # this player's hitbox size and wall footprint. The client just reports its
        # own player and renders the server's enemies as puppets.
        hitbox_w, hitbox_h = player.hitbox.size
        wall_foot = player.wall_foot()
        host = host or MULTIPLAYER_RUNTIME.host
        port = port or MULTIPLAYER_RUNTIME.port
        self.level.mp_client = MultiplayerClient(host, port, player_id)
        self.level.mp_client.send_join(
            character_dir, join_x, join_y,
            hitbox_w=hitbox_w, hitbox_h=hitbox_h, wall_foot=wall_foot, ticket=ticket,
        )
        # The server owns enemies now -> drop any this client spawned during level
        # load before mp_client was set (the spawner is suppressed from here on).
        self.level._clear_local_enemies()
        print(
            f"[multiplayer] connected to {host}:{port} "
            f"as {player_id} ({character_dir}) at ({join_x}, {join_y}); "
            f"hitbox=({hitbox_w}x{hitbox_h}), wall_foot={wall_foot}"
        )

    def _close_multiplayer(self):
        # Send a clean `leave` + shut the socket down before exiting. No-op for
        # singleplayer (mp_client only exists if the multiplayer bootstrap ran).
        level = getattr(self, "level", None)
        client = getattr(level, "mp_client", None) if level is not None else None
        if client is not None:
            client.close()
            level.mp_client = None

    # -- online play: sign in -> Find / Create -> Lobby -> ticket -> match -> Find --

    def open_online(self):
        """Start menu "Play online": the Find screen if signed in, else sign in."""
        if self.online is None:
            self.online = nakama.from_config()
        if self.online is None:
            self.start_menu.notice = "Online play is not set up yet (Code/online/config.json)."
            return
        self.start_menu.notice = ""
        if self.online.signed_in:
            self._enter_find()
        else:
            self.set_state("online_signin")

    def _draw_screen(self, screen):
        """An online screen on the war-room painting."""
        kit = legion_ui.kit_for(self.backend)
        if getattr(self, "_online_scene", None) is None:
            self._online_scene = legion_ui.Scene(kit, "warroom.jpg")
        self._online_scene.draw(self.backend)
        legion_ui.draw(self.backend, kit.shade("dim"), (0, 0))
        screen.draw(self.backend)

    def _back_to_start_menu(self):
        self.in_start_menu = True
        self.start_menu.selected_option = 0
        self.set_state("start_menu")

    def _enter_find(self, notice=""):
        self.find_screen.reset(notice)
        self._refresh_lobbies()
        self.set_state("online_find")

    def _refresh_lobbies(self):
        try:
            reply = self.online.rpc("lobby_list", {"search": self.find_screen.search_text()})
            self.find_screen.set_lobbies(reply.get("lobbies", []))
        except NakamaError as exc:
            self.find_screen.set_notice(str(exc))

    def _join_lobby(self, match_id, password, report):
        """Open the lobby socket if needed and join `match_id`; `report(text)` shows a failure."""
        try:
            if self.lobby_socket is None:
                self.lobby_socket = self.online.open_socket()
            self.lobby_socket.join_match(match_id, {"character": self.online_character,
                                                    "password": password})
        except NakamaError as exc:
            report(str(exc))
            return
        self.lobby_match_id = match_id
        self.lobby_screen.reset(self.online.user_id, self.online_character)
        self.set_state("online_lobby")

    def _leave_lobby(self):
        if self.lobby_socket is not None and self.lobby_match_id is not None:
            try:
                self.lobby_socket.leave_match(self.lobby_match_id)
            except NakamaError:
                pass  # the lobby drops a gone socket by itself
        self.lobby_match_id = None

    def _drop_lobby_socket(self):
        if self.lobby_socket is not None:
            self.lobby_socket.close()
        self.lobby_socket = None
        self.lobby_match_id = None

    def _state_online_signin(self, dt):
        action = self.signin_screen.handle(self.input_manager.events)
        if action is not None:
            if action[0] == "back":
                self._back_to_start_menu()
                return
            try:
                if action[0] == "signin":
                    self.online.login(action[1], action[2])
                else:
                    self.online.register(action[1], action[2], action[3])
            except NakamaError as exc:
                self.signin_screen.set_error(str(exc))
            else:
                self._enter_find()
                return
        self._draw_screen(self.signin_screen)

    def _state_online_find(self, dt):
        action = self.find_screen.handle(self.input_manager.events)
        if action is not None:
            kind = action[0]
            if kind == "back":
                self._drop_lobby_socket()
                self._back_to_start_menu()
                return
            if kind == "refresh":
                self._refresh_lobbies()
            elif kind == "join":
                self._join_lobby(action[1], action[2], self.find_screen.set_notice)
                if self.state != "online_find":
                    return
            elif kind == "create":
                try:
                    maps = self.online.rpc("lobby_maps", {}).get("maps", [])
                except NakamaError as exc:
                    self.find_screen.set_notice(str(exc))
                else:
                    self.create_screen.reset(self.online.username, maps)
                    self.set_state("online_create")
                    return
        self._draw_screen(self.find_screen)

    def _state_online_create(self, dt):
        action = self.create_screen.handle(self.input_manager.events)
        if action is not None:
            if action[0] == "back":
                self._enter_find()
                return
            params = action[1]
            try:
                match_id = self.online.rpc("lobby_create", params)["match_id"]
            except NakamaError as exc:
                self.create_screen.set_error(str(exc))
            else:
                self._join_lobby(match_id, params["password"], self.create_screen.set_error)
                if self.state != "online_create":
                    return
        self._draw_screen(self.create_screen)

    def _state_online_lobby(self, dt):
        for event in self.lobby_socket.poll():
            if event[0] != "match_data":
                # closed / error: the websocket is gone.
                self._drop_lobby_socket()
                self._enter_find("Lost connection to the lobby.")
                return
            _, op, body = event
            if op == OP_STATE:
                self.lobby_screen.set_state(body)
            elif op == OP_NOTICE:
                self.lobby_screen.set_notice(body.get("text", ""))
            elif op == OP_TICKET:
                self._start_online_match(body)
                return
        action = self.lobby_screen.handle(self.input_manager.events)
        if action is not None:
            kind = action[0]
            if kind == "leave":
                self._leave_lobby()
                self._enter_find()
                return
            if kind == "character":
                self.online_character = action[1]
                self.lobby_socket.send(self.lobby_match_id, OP_SET_CHARACTER, {"character": action[1]})
            elif kind == "ready":
                self.lobby_socket.send(self.lobby_match_id, OP_SET_READY, {"ready": action[1]})
            elif kind == "chat":
                self.lobby_socket.send(self.lobby_match_id, OP_CHAT, {"text": action[1]})
            elif kind == "start":
                self.lobby_socket.send(self.lobby_match_id, OP_START, {})
        self._draw_screen(self.lobby_screen)

    def _start_online_match(self, ticket):
        """The lobby handed us a ticket: leave the lobby, load the map, join the match."""
        seat = self.lobby_screen.my_seat()
        character = (seat or {}).get("character") or self.online_character
        self._leave_lobby()
        self._drop_lobby_socket()
        try:
            self._start_multiplayer_session(character, self.online.user_id,
                                            host=ticket["host"], port=int(ticket["port"]),
                                            level_number=int(ticket["map"]), ticket=ticket["ticket"])
        except OSError:
            self._close_multiplayer()
            self.level = None
            self._enter_find("Could not reach the match server.")

    def _end_match(self, reason):
        """The match server is gone or refused us: back to Find (online) or the start menu."""
        self._close_multiplayer()
        self.level = None
        if self.online is not None and self.online.signed_in:
            self._enter_find(reason)
        else:
            self.start_menu.notice = reason
            self._back_to_start_menu()

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
            if RTS_VALIDATION_RUNTIME.enabled:
                layouts_dir = RTS_VALIDATION_RUNTIME.layout_dir
            elif BENCHMARK_RUNTIME.enabled:
                layouts_dir = BENCHMARK_RUNTIME.layout_dir
            else:
                layouts_dir = LEVEL_TO_LAYOUT.get(level_number, DEFAULT_LAYOUT)
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

    def _draw_screen_only(self, dt):
        """The current screen's picture with no input: under the settings overlay."""
        state = self.state
        if state == "level" and self.level and hasattr(self.level, "display_surface"):
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
        elif state == "death_menu":
            self.death_menu.draw()
        elif state == "start_menu":
            self.start_menu.draw()
        elif state == "player_selection":
            self.player_selection.draw()
        elif state == "player_configuration":
            self._draw_player_configuration()
        elif state in ("level_selection", "level_grow"):
            self.level_selection.draw()
        else:
            screen = {
                "online_signin": self.signin_screen,
                "online_find": self.find_screen,
                "online_create": self.create_screen,
                "online_lobby": self.lobby_screen,
            }.get(state)
            if screen is not None:
                self._draw_screen(screen)

    def _state_start_menu(self, dt):
        self.start_menu.handle_events()
        if self.state != "start_menu":
            # "Play online" switched to an online screen: the gate closes over the title.
            self.gate.start(self.start_menu.draw)
            return
        self.start_menu.draw()
        if not self.in_start_menu:
            self.set_state("player_selection")
            self.in_player_selection = True
            self.gate.start(self.start_menu.draw)

    def _state_player_selection(self, dt):
        self.player_selection.handle_events()
        self.player_selection.draw()
        if not self.in_player_selection:
            if self.multiplayer_pending:
                # "Local co-op (dev)" path: skip stat-config / level-selection
                # screens, go straight to level 6 + connect with the just-picked
                # character. player_id must be unique per process (two clients
                # sharing an id = the server treats them as one player).
                player_id = os.getenv("PRCH_MULTIPLAYER_PLAYER_ID") or f"player-{os.getpid()}"
                self._start_multiplayer_session(
                    self.player_selection.selected_player_info_dir, player_id
                )
                return
            self.set_state("player_configuration")
            selected_player_base_stats = self.player_selection.base_stats
            _game_flow_log.debug("BASE STATS: ")
            _game_flow_log.debug("%s", selected_player_base_stats)
            self.player_configuration = PlayerConfiguration(
                input_manager=self.input_manager,
                base_stats=selected_player_base_stats,
                remaining_points=10,
                game=self,
                title=unlocked_player_display_names[self.player_selection.selected_option],
            )
            # The attributes stand on the shrine beside the hero just picked.
            self.player_configuration.stage = self.player_selection.draw_stage

    def _draw_player_configuration(self):
        self.player_configuration.draw(self.backend)

    def _state_player_configuration(self, dt):
        self.player_configuration.handle_events()
        self._draw_player_configuration()
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
            if self.level_selection.chosen is None:
                self.start_level(self.level_selection.selected_level)
                return
            picture, card = self.level_selection.chosen
            self.grow = Grow(self.level_selection._kit, picture, card)
            self.set_state("level_grow")

    def _state_level_grow(self, dt):
        """The chosen card grows until it covers the window, then the level is built behind
        it, so the build's stall shows the level's picture."""
        self.level_selection.draw()
        self.grow.draw(self.backend)
        if self.grow.done:
            if getattr(self.grow, "shown", False):
                self.grow = None
                self.start_level(self.level_selection.selected_level)
            else:
                self.grow.shown = True  # one frame at full size reaches the screen first

    def _state_level(self, dt):
        self.level.run(dt)
        end_reason = getattr(self.level, "mp_end_reason", None)
        if end_reason:
            self._end_match(end_reason)
            return
        if getattr(self.level, "player_dead", False):
            self.set_state("death_menu")

    def _state_death_menu(self, dt):
        self.death_menu.draw()
        action = self.death_menu.handle_events()
        in_match = getattr(self.level, "mp_client", None) is not None
        if action == "restart" and in_match:
            # Restarting would load a fresh single-player level and leave the match
            # socket open; a match is left the same way as "main menu".
            action = "main_menu"
        # Restart and main menu go through the gate; a level is built while it is shut.
        if action == "restart":
            if self.current_level_number is not None:
                level_number = self.current_level_number
                self.gate.start(self.death_menu.draw, lambda: self.start_level(level_number))
        elif action == "main_menu" and in_match:
            self.gate.start(self.death_menu.draw, lambda: self._end_match(""))
        elif action == "main_menu":
            self.gate.start(self.death_menu.draw, self._death_to_start_menu)
        elif action == "exit":
            self._close_multiplayer()
            pygame.quit()
            sys.exit()

    def _death_to_start_menu(self):
        self.level = None
        self.in_start_menu = True
        self.in_player_selection = False
        self.in_level_selection = False
        self.start_menu.selected_option = 0
        self.level_selection.selected_level = None
        self.set_state("start_menu")

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
            if self.gate.busy:
                # No input while the gate runs; key releases still pass, so held keys let go.
                events = [e for e in events if e.type in (pygame.KEYUP, pygame.QUIT)]
            self._handle_global_shortcuts(events)
            self.input_manager.update(events)

            for event in events:
                if event.type == pygame.QUIT:
                    exit_code = 0
                    if RTS_VALIDATION_RUNTIME.shutdown_requested:
                        exit_code = RTS_VALIDATION_RUNTIME.shutdown_exit_code
                    self._close_multiplayer()
                    pygame.quit()
                    sys.exit(exit_code)

            if self.settings_menu.visible:
                self.settings_menu.handle_events(events)

            self.apply_settings()
            self.gate.update()

            if self.settings_menu.visible:
                # Pause normal state handlers while settings menu is active.
                self._draw_screen_only(dt)
            elif self.gate.closing:
                # The old screen, with no input, until the leaves meet.
                self.gate.behind()
            else:
                self._dispatch_state(dt)

            if self.show_debug_info:
                self.update_debug_info()
                self.display_debug_info()

            self.settings_menu.draw(self.backend)
            self.gate.draw()

            self._maybe_save_shot()
            self.backend.present()
            frame_ms = self.clock.tick(self.settings.fps_cap)
            self._maybe_log_frames(frame_ms)
            dt = frame_ms / 1000

    def _maybe_log_frames(self, frame_ms):
        """Overlay-off frame times (PRCH_FRAME_LOG=1). Median after a warmup, then exit."""
        if os.environ.get("PRCH_FRAME_LOG", "0") == "0":
            return
        if self.state != "level":
            return
        warmup = int(os.environ.get("PRCH_FRAME_LOG_WARMUP", "30"))
        count = int(os.environ.get("PRCH_FRAME_LOG_COUNT", "60"))
        seen = getattr(self, "_flog_seen", 0) + 1
        self._flog_seen = seen
        if seen <= warmup:
            return
        samples = getattr(self, "_flog", None)
        if samples is None:
            samples = []
            self._flog = samples
        samples.append(frame_ms)
        if len(samples) < count:
            return
        ordered = sorted(samples)
        median = ordered[len(ordered) // 2]
        mean = sum(ordered) / len(ordered)
        rss = psutil.Process(os.getpid()).memory_info().rss / 1024 ** 2
        print(
            f"[FRAME] n={len(ordered)} median_ms={median:.1f} mean_ms={mean:.1f} rss_mb={rss:.0f}",
            flush=True,
        )
        pygame.quit()
        sys.exit(0)

    def _maybe_save_shot(self):
        """One-shot framebuffer dump for mesh/sprite A/B (PRCH_SHOT_PATH + PRCH_SHOT_FRAME)."""
        path = os.environ.get("PRCH_SHOT_PATH")
        if not path or getattr(self, "_shot_done", False):
            return
        self._shot_frames = getattr(self, "_shot_frames", 0) + 1
        want = int(os.environ.get("PRCH_SHOT_FRAME", "45"))
        if self._shot_frames < want or self.state != "level":
            return
        from OpenGL.GL import GL_RGBA, GL_UNSIGNED_BYTE, glFinish, glReadPixels
        import numpy as np
        glFinish()
        w, h = self.backend.get_size()
        pixels = glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE)
        arr = np.flipud(np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 4))
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        pygame.image.save(pygame.image.frombytes(arr.tobytes(), (w, h), "RGBA"), path)
        self._shot_done = True
        print(f"[shot] wrote {path} at frame {self._shot_frames}", flush=True)
        if os.environ.get("PRCH_SHOT_EXIT", "0") != "0":
            pygame.quit()
            sys.exit(0)


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
            # GPU batching: atlas-hit blits batch; the other two each force a draw call.
            self.debug_blit_stats = getattr(self.backend, "last_blit_stats", None)
            if self.debug_blit_stats is not None:
                atlas, keyed, nokey = self.debug_blit_stats
                total = atlas + keyed + nokey
                hit_pct = (100 * atlas // total) if total else 0
                # Tagged so it can be grepped out of a captured run log.
                print(f"[BLIT] last-frame atlas-hit={atlas} ({hit_pct}%) "
                      f"flush_keyed_miss={keyed} flush_nokey={nokey} total={total}",
                      flush=True)


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

        # GPU batching diagnostic (last frame): atlas-batched vs flush-forcing blits.
        if self.debug_blit_stats is not None:
            atlas, keyed, nokey = self.debug_blit_stats
            flushes = keyed + nokey
            total = atlas + flushes
            hit_pct = (100 * atlas // total) if total else 0
            debug_info.append(("Blit Atlas", f"Blit atlas-hit: {atlas} ({hit_pct}%)"))
            debug_info.append(("Blit Flush", f"Blit flush: {flushes} (keyed-miss {keyed} / nokey {nokey})"))

        for key, value in debug_info:
            # Check if the surface needs to be updated
            if key not in self.debug_info_surfaces or self.debug_info_surfaces[key]['value'] != value:
                # Free the old GPU texture (keyed by surface id) before discarding the surface
                if key in self.debug_info_surfaces:
                    self.backend.invalidate_texture(self.debug_info_surfaces[key]['surface'])
                # Render new text surface and cache it
                text_surface = font.render(value, True, pygame.Color('white'))
                self.debug_info_surfaces[key] = {'surface': text_surface, 'value': value}

            # Blit the cached text surface — cache_key=id(surface) lets the GPU backend
            # upload it once and reuse the texture every frame instead of re-uploading.
            surf = self.debug_info_surfaces[key]['surface']
            self.backend.blit(surf, (10, current_y), cache_key=id(surf))
            current_y -= text_spacing


if  __name__ == "__main__":
    game = Game()
    game.run()
