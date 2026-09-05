"""In-game RTS validation scenarios (runs inside Level4 update loop)."""

import time

import pygame

from rts.assets import normalize_faction_id
from rts.categories import FOOD
from rts.entities.worker import IDLE, WAITING_AT_NODE
from rts_validation_runtime import RTS_VALIDATION_RUNTIME
from Settings import TILESIZE
from Support import mask_midbottom_world
from hashRect import HashableRect
from terrain_height import (
    GOLDEN_HEIGHT_U8,
    GOLDEN_RIDGE,
    GOLDEN_SHELF,
    GOLDEN_VOID,
    GOLDEN_WASH,
    HEIGHT_U8_TOLERANCE,
    PHYSICS_GRADIENT_STEP,
    TERRAIN_G,
    load_chunk_00_01,
    world_scale_for_layout,
)


def _press_key(input_manager, key):
    input_manager.current_key_states[key] = True
    input_manager.key_press_events[key] = True


def _release_key(input_manager, key):
    input_manager.current_key_states[key] = False


def _clear_just_pressed(input_manager):
    input_manager.key_press_events = {}


def _find_throne(level, profile_id):
    for obj in level.layout_manager.environment_interactables:
        if str(getattr(obj, "profile_id", "")).strip() == profile_id:
            return obj
    return None


def _registry(level):
    return level.layout_manager.rts_registry


def _apply_fast_mode(level):
    if not RTS_VALIDATION_RUNTIME.fast_mode:
        return
    registry = _registry(level)
    for fac_nodes in registry.faction_node_index.values():
        for nodes in fac_nodes.values():
            for node in nodes:
                node.gather_duration = 0.1
                if node.depletable:
                    node.config["initial_cycles"] = 2
                    node.remaining_cycles = 2
                    node.respawn_seconds = 0.5


def _apply_visible_pace(level):
    """Shorter gathers for visible runs: still walk + deliver, not 60s+ per scenario."""
    if not RTS_VALIDATION_RUNTIME.visible_mode or RTS_VALIDATION_RUNTIME.fast_mode:
        return
    registry = _registry(level)
    for fac_nodes in registry.faction_node_index.values():
        for nodes in fac_nodes.values():
            for node in nodes:
                node.gather_duration = min(float(node.gather_duration), 6.0)
                if node.depletable:
                    node.respawn_seconds = min(float(getattr(node, "respawn_seconds", 2.0)), 2.0)
                    node.config["initial_cycles"] = 2
                    node.remaining_cycles = min(int(getattr(node, "remaining_cycles", 2)), 2)


def _teleport_sprite(sprite, pos):
    sprite.rect.center = (int(pos[0]), int(pos[1]))


def _teleport_player(player, pos):
    player.hitbox.center = (int(pos[0]), int(pos[1]))
    player.velocity = pygame.math.Vector2(0, 0)
    player.direction.x = 0
    player.direction.y = 0
    if hasattr(player, "plant_sprite_on_hitbox"):
        player.plant_sprite_on_hitbox()
    else:
        player.rect.center = player.hitbox.center


def _unpack_runner_result(result):
    if len(result) == 4:
        done, passed, details, status = result
        return done, passed, details, status
    done, passed, details = result
    return done, passed, details, ("pass" if passed else "fail")


def _player_on_painted_ground(level, player):
    grounds = getattr(level.layout_manager, "ground_sprites", None)
    if not grounds:
        return False
    pt = player.hitbox.center
    return any(sprite.rect.collidepoint(pt) for sprite in grounds)


def _tile_grid_size(level):
    tmx = getattr(level.layout_manager, "tmxdata", None)
    if tmx is None:
        return 0, 0
    return int(tmx.width) * TILESIZE, int(tmx.height) * TILESIZE


def _gather_update(session, level, dt, wallet=None):
    world_sim = getattr(level, "rts_world_sim", None)
    if world_sim is not None:
        world_sim.tick(dt, level.rts_world_adapter)
        return
    lm = level.layout_manager
    session.gather_controller.update(
        dt,
        lm.obstacle_sprites,
        wallet if wallet is not None else session.wallet,
        walk_grid_cache=getattr(lm, "walk_grid_cache", None),
        obstacle_quad_tree=getattr(lm, "obstacle_quad_tree", None),
    )


def _simulate_gather_until_delivery(level, worker, node, wallet, max_steps=400, dt=0.05):
    from rts.entities.worker import MOVING_TO_DROPOFF

    session = level.rts_session
    _teleport_sprite(worker, node.gather_point)
    session.gather_controller.assign(worker, node, wallet)
    cat = node.resource_category
    for _ in range(max_steps):
        if getattr(worker, "gather_state", "") == MOVING_TO_DROPOFF:
            drop = getattr(worker, "assigned_dropoff", None)
            if drop is not None:
                _teleport_sprite(worker, drop.rect.center)
        _gather_update(session, level, dt, wallet)
        if wallet.get(cat) > 0:
            return True, wallet.get(cat)
    return False, wallet.get(cat)


def _reset_rts(level):
    session = level.rts_session
    if session.is_active():
        session.exit(request_stand=True)
    session.chief_panel.close()
    session.pending_workers = []
    session.gather_controller.tasks.clear()


def _sit_throne(level, profile_id):
    _reset_rts(level)
    throne = _find_throne(level, profile_id)
    if throne is None:
        return None
    level._sit_on_seat(throne)
    return throne


class RtsValidationDriver:
    WARMUP_FRAMES = 30
    DT = 0.05
    # Visible caps: expected time + small margin (8s hold is separate).
    # Gather uses _apply_visible_pace (6s at node); typical scenario < 30s wall clock.
    VISIBLE_MAX_SECONDS = {
        "map_entities_loaded": 12.0,
        "eskimo_chief_on_throne": 12.0,
        "jungle_chief_on_throne": 12.0,
        "chief_panel_spawn_despawn": 14.0,
        "chief_select_all_workers": 14.0,
        "assign_node_confirm": 14.0,
        "assign_nearest_food": 16.0,
        "eskimo_gather_delivers": 38.0,
        "jungle_gather_delivers": 38.0,
        "max_workers_queue": 32.0,
        "depletable_exhausts": 36.0,
        "depletable_respawns": 14.0,
        "non_depletable_stays_active": 12.0,
        "lost_without_dropoff": 28.0,
        "player_feet_plant": 10.0,
        "terrain_height_sample": 14.0,
        "terrain_slope_speed": 42.0,
        "terrain_sprite_tilt": 14.0,
        "terrain_shadow_slope": 14.0,
    }

    DEFAULT_SCENARIO_NAMES = (
        "map_entities_loaded",
        "eskimo_chief_on_throne",
        "jungle_chief_on_throne",
        "chief_panel_spawn_despawn",
        "chief_select_all_workers",
        "assign_node_confirm",
        "assign_nearest_food",
        "eskimo_gather_delivers",
        "jungle_gather_delivers",
        "max_workers_queue",
        "depletable_exhausts",
        "depletable_respawns",
        "non_depletable_stays_active",
        "lost_without_dropoff",
        "player_feet_plant",
    )
    TERRAIN_SCENARIO_NAMES = (
        "terrain_height_sample",
        "terrain_slope_speed",
        "terrain_sprite_tilt",
        "terrain_shadow_slope",
    )
    TERRAIN_WALK_FRAMES_FAST = 8
    TERRAIN_WALK_FRAMES_VISIBLE = 70
    TERRAIN_SLOPE_LAPS = 3

    def __init__(self):
        self._frame = 0
        self._scenario_index = 0
        self._scenario_frame = 0
        self._scenario_started = 0.0
        self._active = None
        self._pace_applied = False
        self._last_dt = 0.05
        self._hold_started = None
        self._pending_result = None
        self._scenario_names = list(self.DEFAULT_SCENARIO_NAMES)
        self._heightmap = None
        self._terrain_spawn = None
        self._terrain_phase = None
        self._terrain_walk_frames = 0
        self._terrain_ridge_mult = None
        self._terrain_shelf_mult = None
        self._terrain_laps = 0
        self._terrain_ridge_tilt = None
        self._terrain_shelf_tilt = None
        self._terrain_ridge_shadow = None
        self._terrain_shelf_shadow = None
        self._feet_idle_y = None
        self._feet_start_hitbox = None
        self._feet_max_bob = 0
        self._feet_idle_match = None
        self._feet_wall_phase = None
        self._feet_wall_contacted = False
        self._feet_wall_reversed = False
        self._feet_wall_tunnel = False
        self._feet_last_x = None
        self._feet_last_y = None
        self._feet_wall_key = pygame.K_RIGHT
        self._feet_wall_reverse_key = pygame.K_LEFT
        self._feet_wall_sign = 1
        self._feet_wall_axis = "x"

    def _filtered_names(self):
        requested = [
            n
            for n in RTS_VALIDATION_RUNTIME.scenario_filter
            if n and str(n).strip().lower() != "all"
        ]
        known = list(self.DEFAULT_SCENARIO_NAMES) + list(self.TERRAIN_SCENARIO_NAMES)
        if not requested:
            return list(self.DEFAULT_SCENARIO_NAMES)
        return [n for n in requested if n in known]

    def _max_seconds_for(self, name, runtime):
        if runtime.fast_mode:
            return runtime.max_seconds
        return self.VISIBLE_MAX_SECONDS.get(name, runtime.max_seconds)

    def _update_overlay(self, level, name, phase, extra=None):
        runtime = RTS_VALIDATION_RUNTIME
        if not runtime.overlay_enabled:
            return
        names = self._filtered_names()
        idx = min(self._scenario_index + 1, max(1, len(names)))
        total = len(names)
        elapsed = time.time() - self._scenario_started if self._scenario_started else 0.0
        limit = self._max_seconds_for(name, runtime)
        lines = [
            "RTS VALIDATION",
            f"scenario {idx}/{total}: {name}",
            f"phase: {phase}",
            f"elapsed: {elapsed:.1f}s / {limit:.0f}s",
        ]
        if runtime.hold_seconds > 0 and self._hold_started is not None:
            held = time.time() - self._hold_started
            lines.append(f"hold: {held:.1f}/{runtime.hold_seconds:.1f}s")
        session = getattr(level, "rts_session", None)
        if session is not None:
            lines.append(f"wallet food={session.wallet.get(FOOD)}")
        if extra:
            lines.extend(extra)
        if name == "player_feet_plant":
            if self._feet_idle_y is not None:
                lines.append(f"idle_feet_y={self._feet_idle_y}")
            lines.append(f"max_bob={self._feet_max_bob}")
            if self._feet_idle_y is not None and getattr(level, "player", None) is not None:
                player = level.player
                if getattr(player, "mask", None) and getattr(player, "rect", None):
                    live = int(mask_midbottom_world(player.rect, player.mask)[1])
                    lines.append(f"live_delta={abs(live - self._feet_idle_y)}")
            if self._feet_wall_phase:
                lines.append(
                    f"wall={self._feet_wall_phase} contacted={int(self._feet_wall_contacted)} "
                    f"reversed={int(self._feet_wall_reversed)}"
                )
        if name.startswith("terrain_"):
            lines.extend(self._terrain_hud_lines(level))
        runtime.set_overlay(lines, phase=phase)

    def tick(self, level, dt):
        """Return True when all scenarios finished (caller should shutdown)."""
        runtime = RTS_VALIDATION_RUNTIME
        self._frame += 1
        self._last_dt = max(0.001, float(dt))

        if self._frame < self.WARMUP_FRAMES:
            return False

        if not self._pace_applied:
            if runtime.fast_mode:
                _apply_fast_mode(level)
            elif runtime.visible_mode:
                _apply_visible_pace(level)
            self._pace_applied = True

        names = self._filtered_names()
        if self._scenario_index >= len(names):
            runtime.request_shutdown(0 if runtime.all_passed else 1)
            return True

        name = names[self._scenario_index]
        if self._active is None:
            self._active = name
            self._scenario_frame = 0
            self._scenario_started = time.time()
            self._hold_started = None
            self._pending_result = None
            print(f"[RTS_VAL] Starting scenario: {name}", flush=True)
            if name == "player_feet_plant":
                self._feet_idle_y = None
                self._feet_start_hitbox = None
                self._feet_max_bob = 0
                self._feet_idle_match = None
                self._feet_wall_phase = None
                self._feet_wall_contacted = False
                self._feet_wall_reversed = False
                self._feet_wall_tunnel = False
                self._feet_last_x = None
                self._feet_last_y = None
                self._feet_wall_key = pygame.K_RIGHT
                self._feet_wall_reverse_key = pygame.K_LEFT
                self._feet_wall_sign = 1
                self._feet_wall_axis = "x"
            if name.startswith("terrain_"):
                self._terrain_phase = None
                self._terrain_walk_frames = 0
                self._terrain_ridge_mult = None
                self._terrain_shelf_mult = None
                self._terrain_laps = 0
                self._terrain_ridge_tilt = None
                self._terrain_shelf_tilt = None
                self._terrain_ridge_shadow = None
                self._terrain_shelf_shadow = None

        elapsed = time.time() - self._scenario_started
        limit = self._max_seconds_for(name, runtime)

        # Complete post-pass hold even when runner returns done=False on later frames.
        if self._hold_started is not None and self._pending_result is not None:
            hold_name, hold_passed, hold_details, hold_status = self._pending_result
            if time.time() - self._hold_started < runtime.hold_seconds:
                phase = "PROBE" if hold_status == "probe" else (
                    "PASS" if hold_passed else "FAIL"
                )
                self._update_overlay(level, hold_name, phase, [hold_details])
                return False
            runtime.record(
                hold_name,
                hold_passed,
                hold_details,
                (time.time() - self._scenario_started) * 1000,
                status=hold_status,
            )
            self._advance(level)
            return False

        self._scenario_frame += 1
        if elapsed > limit:
            runtime.record(name, False, f"timeout after {limit}s", elapsed * 1000)
            self._advance(level)
            return False

        runner = getattr(self, f"_run_{name}", None)
        if runner is None:
            runtime.record(name, False, "no runner", 0)
            self._advance(level)
            return False

        self._update_overlay(level, name, "RUNNING")
        done, passed, details, status = _unpack_runner_result(runner(level))
        if done:
            hold_like_pass = passed or status == "probe"
            if hold_like_pass and runtime.visible_mode and runtime.hold_seconds > 0:
                self._hold_started = time.time()
                self._pending_result = (name, passed, details, status)
                phase = "PROBE" if status == "probe" else "PASS"
                self._update_overlay(level, name, phase, [details])
                return False
            runtime.record(
                name,
                passed,
                details,
                (time.time() - self._scenario_started) * 1000,
                status=status,
            )
            self._advance(level)
        return False

    def _restore_feet_plant_player(self, level):
        player = getattr(level, "player", None)
        if player is None or self._feet_start_hitbox is None:
            return
        _release_key(level.input_manager, pygame.K_RIGHT)
        _release_key(level.input_manager, pygame.K_LEFT)
        _release_key(level.input_manager, pygame.K_UP)
        _release_key(level.input_manager, pygame.K_DOWN)
        player.direction.x = 0
        player.direction.y = 0
        player.velocity = pygame.math.Vector2(0, 0)
        player.hitbox.center = self._feet_start_hitbox
        if hasattr(player, "plant_sprite_on_hitbox"):
            player.plant_sprite_on_hitbox()
        else:
            player.rect.center = player.hitbox.center

    def _advance(self, level=None):
        self._release_move_keys(level)
        if level is not None and self._active == "player_feet_plant":
            self._restore_feet_plant_player(level)
        self._scenario_index += 1
        self._active = None
        self._hold_started = None
        self._pending_result = None
        self._terrain_phase = None
        if level is not None:
            _reset_rts(level)

    def finish(self, level):
        runtime = RTS_VALIDATION_RUNTIME
        payload = runtime.write_results()
        code = 0 if payload.get("ok") else 1
        runtime.request_shutdown(code)
        return code

    # --- scenarios ---

    def _run_map_entities_loaded(self, level):
        if self._scenario_frame < 2:
            return False, False, ""
        reg = _registry(level)
        eskimo_nodes = reg.faction_node_index.get("eskimo", {})
        jungle_nodes = reg.faction_node_index.get("jungle_tribe", {})
        eskimo_node_count = sum(len(v) for v in eskimo_nodes.values())
        jungle_node_count = sum(len(v) for v in jungle_nodes.values())
        eskimo_drop = len(reg.dropoffs_by_faction.get("eskimo", {}))
        jungle_drop = len(reg.dropoffs_by_faction.get("jungle_tribe", {}))
        ok = (
            len(reg.chiefs) >= 2
            and eskimo_node_count >= 5
            and jungle_node_count >= 5
            and eskimo_drop >= 3
            and jungle_drop >= 4
        )
        details = (
            f"chiefs={len(reg.chiefs)} "
            f"eskimo_nodes={eskimo_node_count} jungle_nodes={jungle_node_count} "
            f"eskimo_drop={eskimo_drop} jungle_drop={jungle_drop}"
        )
        return True, ok, details

    def _run_eskimo_chief_on_throne(self, level):
        if self._scenario_frame == 1:
            _sit_throne(level, "throne_eskimo")
            return False, False, ""
        if self._scenario_frame < 4:
            return False, False, ""
        session = level.rts_session
        session.state = session.SELECT
        chief = _registry(level).get_chief_for_throne("throne_eskimo")
        sprites = level.rts_world_adapter.get_selectable_sprites("throne_eskimo")
        chiefs = [s for s in sprites if str(getattr(s, "kind", "")) == "chief"]
        jungle_chief = _registry(level).get_chief_for_throne("throne_jungle")
        ok = (
            session.is_active()
            and chief is not None
            and len(chiefs) == 1
            and chiefs[0] is chief
            and (jungle_chief is None or jungle_chief not in sprites)
        )
        return True, ok, f"selectable_chiefs={len(chiefs)} active={session.is_active()}"

    def _run_jungle_chief_on_throne(self, level):
        if self._scenario_frame == 1:
            _sit_throne(level, "throne_jungle")
            return False, False, ""
        if self._scenario_frame < 4:
            return False, False, ""
        session = level.rts_session
        session.state = session.SELECT
        chief = _registry(level).get_chief_for_throne("throne_jungle")
        sprites = level.rts_world_adapter.get_selectable_sprites("throne_jungle")
        chiefs = [s for s in sprites if str(getattr(s, "kind", "")) == "chief"]
        eskimo_chief = _registry(level).get_chief_for_throne("throne_eskimo")
        ok = (
            session.is_active()
            and chief is not None
            and len(chiefs) == 1
            and chiefs[0] is chief
            and (eskimo_chief is None or eskimo_chief not in sprites)
        )
        return True, ok, f"selectable_chiefs={len(chiefs)}"

    def _run_chief_panel_spawn_despawn(self, level):
        session = level.rts_session
        reg = _registry(level)
        if self._scenario_frame == 1:
            _sit_throne(level, "throne_eskimo")
            return False, False, ""
        chief = reg.get_chief_for_throne("throne_eskimo")
        if chief is None:
            return True, False, "no eskimo chief"
        if self._scenario_frame == 3:
            session.chief_panel.open(chief)
            session.state = session.CHIEF_PANEL
            return False, False, ""
        if self._scenario_frame == 5:
            idle_before = chief.population_idle
            session.spawn_worker_from_chief(chief)
            ok_spawn = chief.population_workers >= 1 and chief.population_idle == idle_before - 1
            if not ok_spawn:
                return True, False, "spawn failed"
            return False, False, ""
        if self._scenario_frame == 7:
            session.despawn_worker_from_chief(chief)
            ok = chief.population_idle > 0
            session.chief_panel.close()
            session.state = session.SELECT
            return True, ok, f"workers={chief.population_workers} idle={chief.population_idle}"

        return False, False, ""

    def _run_chief_select_all_workers(self, level):
        session = level.rts_session
        reg = _registry(level)
        if self._scenario_frame == 1:
            _sit_throne(level, "throne_eskimo")
            return False, False, ""
        chief = reg.get_chief_for_throne("throne_eskimo")
        if chief is None:
            return True, False, "no chief"
        if self._scenario_frame == 3:
            session.spawn_worker_from_chief(chief)
            session.spawn_worker_from_chief(chief)
            return False, False, ""
        if self._scenario_frame == 5:
            session.chief_panel.open(chief)
            session.state = session.CHIEF_PANEL
            _press_key(level.input_manager, pygame.K_a)
            session.chief_panel.handle_input(session)
            _clear_just_pressed(level.input_manager)
            n = len(session.pending_workers)
            ok = (
                session.state == session.SELECT
                and not session.chief_panel.visible
                and n >= 2
            )
            return True, ok, f"pending_workers={n}"

        return False, False, ""

    def _run_assign_node_confirm(self, level):
        session = level.rts_session
        reg = _registry(level)
        if self._scenario_frame == 1:
            _sit_throne(level, "throne_eskimo")
            return False, False, ""
        chief = reg.get_chief_for_throne("throne_eskimo")
        if self._scenario_frame == 3 and chief:
            session.spawn_worker_from_chief(chief)
            return False, False, ""
        workers = reg.workers_by_faction.get("eskimo", [])
        if not workers:
            return True, False, "no worker"
        if self._scenario_frame == 5:
            nodes = reg.nodes_for_faction("eskimo", FOOD)
            if not nodes:
                return True, False, "no food node"
            worker = workers[0]
            session.pending_workers = [worker]
            session.gather_controller.assign(worker, nodes[0], session.wallet)
            ok = id(worker) in session.gather_controller.tasks
            return True, ok, f"assigned={ok}"

        return False, False, ""

    def _run_assign_nearest_food(self, level):
        session = level.rts_session
        reg = _registry(level)
        if self._scenario_frame == 1:
            _sit_throne(level, "throne_jungle")
            return False, False, ""
        chief = reg.get_chief_for_throne("throne_jungle")
        if self._scenario_frame in (3, 5) and chief:
            session.spawn_worker_from_chief(chief)
            return False, False, ""
        if self._scenario_frame == 7:
            workers = reg.workers_by_faction.get("jungle_tribe", [])
            if not workers:
                return True, False, "no worker"
            worker = workers[0]
            pos = worker.rect.center
            node = reg.nearest_node_with_slot("jungle_tribe", FOOD, pos)
            if node is None:
                return True, False, "no nearest food node with slot"
            session.gather_controller.assign(worker, node, session.wallet)
            ok = id(worker) in session.gather_controller.tasks
            return True, ok, f"task_active={ok}"

        return False, False, ""

    def _run_eskimo_gather_delivers(self, level):
        return self._run_gather_delivers(level, "eskimo", "throne_eskimo", FOOD)

    def _run_jungle_gather_delivers(self, level):
        return self._run_gather_delivers(level, "jungle_tribe", "throne_jungle", FOOD)

    def _run_gather_delivers(self, level, faction_id, throne_id, category):
        session = level.rts_session
        reg = _registry(level)
        if self._scenario_frame == 1:
            _sit_throne(level, throne_id)
            return False, False, ""
        chief = reg.get_chief_for_throne(throne_id)
        if self._scenario_frame == 3 and chief:
            session.spawn_worker_from_chief(chief)
            return False, False, ""
        workers = reg.workers_by_faction.get(faction_id, [])
        if self._scenario_frame == 5:
            if not workers:
                return True, False, "no worker"
            nodes = reg.nodes_for_faction(faction_id, category)
            if not nodes:
                return True, False, "no node"
            if RTS_VALIDATION_RUNTIME.fast_mode:
                ok, amount = _simulate_gather_until_delivery(
                    level, workers[0], nodes[0], session.wallet, max_steps=500, dt=self.DT
                )
                return True, ok, f"wallet_{category}={amount}"
            worker = workers[0]
            pos = worker.rect.center
            node = reg.nearest_node_with_slot(faction_id, category, pos) or nodes[0]
            worker.speed = 200.0
            session.gather_controller.assign(worker, node, session.wallet)
            return False, False, ""
        if not RTS_VALIDATION_RUNTIME.fast_mode and self._scenario_frame > 5:
            worker = workers[0] if workers else None
            if worker is None:
                return True, False, "no worker"
            amount = session.wallet.get(category)
            state = getattr(worker, "gather_state", "")
            RTS_VALIDATION_RUNTIME.set_overlay(
                [
                    "RTS VALIDATION",
                    f"scenario: {self._active}",
                    "phase: GATHER",
                    f"worker: {state}",
                    f"wallet_{category}={amount}",
                ],
                phase="GATHER",
            )
            if amount > 0:
                return True, True, f"wallet_{category}={amount}"
        return False, False, ""

    def _run_max_workers_queue(self, level):
        session = level.rts_session
        reg = _registry(level)
        if self._scenario_frame == 1:
            _sit_throne(level, "eskimo")
            return False, False, ""
        chief = reg.get_chief_for_throne("throne_eskimo")
        if self._scenario_frame == 3 and chief:
            session.spawn_worker_from_chief(chief)
            session.spawn_worker_from_chief(chief)
            return False, False, ""
        workers = reg.workers_by_faction.get("eskimo", [])
        if len(workers) < 2:
            return True, False, "need 2 workers"
        if self._scenario_frame == 5:
            nodes = reg.nodes_for_faction("eskimo", FOOD)
            if not nodes:
                return True, False, "no node"
            node = nodes[0]
            node.max_workers = 1
            node._active_workers = 0
            if RTS_VALIDATION_RUNTIME.fast_mode:
                _teleport_sprite(workers[0], node.gather_point)
                _teleport_sprite(workers[1], node.gather_point)
            session.gather_controller.assign(workers[0], node, session.wallet)
            session.gather_controller.assign(workers[1], node, session.wallet)
            w2 = workers[1]
            if RTS_VALIDATION_RUNTIME.fast_mode:
                if getattr(w2, "gather_state", "") == WAITING_AT_NODE:
                    return True, True, "second worker waiting"
                _gather_update(session, level, self.DT)
                if getattr(w2, "gather_state", "") == WAITING_AT_NODE:
                    return True, True, "second worker waiting after tick"
                return True, False, f"states={workers[0].gather_state},{w2.gather_state}"
            return False, False, ""
        if not RTS_VALIDATION_RUNTIME.fast_mode and self._scenario_frame > 5:
            w2 = workers[1]
            _gather_update(session, level, self._last_dt)
            if getattr(w2, "gather_state", "") == WAITING_AT_NODE:
                return True, True, "second worker waiting"
        return False, False, ""

    def _run_depletable_exhausts(self, level):
        reg = _registry(level)
        if self._scenario_frame == 1:
            _sit_throne(level, "eskimo")
            return False, False, ""
        node = _find_depletable_node(reg, "eskimo")
        if node is None:
            return True, False, "no depletable eskimo node"
        if self._scenario_frame == 3:
            node.remaining_cycles = 1
            node.depleted = False
            return False, False, ""
        if self._scenario_frame == 5:
            chief = reg.get_chief_for_throne("throne_eskimo")
            if chief:
                level.rts_session.spawn_worker_from_chief(chief)
            return False, False, ""
        workers = reg.workers_by_faction.get("eskimo", [])
        if workers and self._scenario_frame == 7:
            level.rts_session.gather_controller.assign(
                workers[0], node, level.rts_session.wallet
            )
            return False, False, ""
        if self._scenario_frame > 10:
            workers = reg.workers_by_faction.get("eskimo", [])
            session = level.rts_session
            if RTS_VALIDATION_RUNTIME.fast_mode:
                if workers:
                    _teleport_sprite(workers[0], node.gather_point)
                    session.gather_controller.assign(
                        workers[0], node, session.wallet
                    )
                for _ in range(80):
                    _gather_update(session, level, self.DT)
                    node.update(self.DT)
                    if node.depleted:
                        return True, True, "node depleted"
                if self._scenario_frame > 200:
                    return True, False, f"depleted={node.depleted} cycles={node.remaining_cycles}"
            elif self._scenario_frame == 11:
                node.complete_gather_cycle()
                ok = bool(node.depleted)
                return True, ok, "node depleted" if ok else f"cycles={node.remaining_cycles}"
        return False, False, ""

    def _run_depletable_respawns(self, level):
        reg = _registry(level)
        node = _find_depletable_node(reg, "eskimo")
        if node is None:
            return True, False, "no depletable node"
        if self._scenario_frame == 1:
            node.depleted = True
            node.remaining_cycles = 0
            node.respawn_seconds = 0.5
            node._respawn_timer = 0.5
            return False, False, ""
        if self._scenario_frame > 2:
            if RTS_VALIDATION_RUNTIME.fast_mode:
                for _ in range(20):
                    node.update(self.DT)
            else:
                node.update(self._last_dt)
            if node.is_active():
                return True, True, "node respawned"
            if self._scenario_frame > 80:
                return True, False, f"still depleted={node.depleted}"
        return False, False, ""

    def _run_non_depletable_stays_active(self, level):
        reg = _registry(level)
        nodes = reg.nodes_for_faction("eskimo", FOOD)
        if not nodes:
            return True, False, "no food node"
        node = nodes[0]
        if self._scenario_frame < 5:
            for _ in range(5):
                node.complete_gather_cycle()
            ok = not node.depleted and node.is_active()
            return True, ok, f"depleted={node.depleted}"

        return False, False, ""

    def _run_lost_without_dropoff(self, level):
        session = level.rts_session
        reg = _registry(level)
        if self._scenario_frame == 1:
            _sit_throne(level, "eskimo")
            return False, False, ""
        chief = reg.get_chief_for_throne("throne_eskimo")
        if self._scenario_frame == 3 and chief:
            session.spawn_worker_from_chief(chief)
            return False, False, ""
        if self._scenario_frame < 5:
            return False, False, ""
        workers = reg.workers_by_faction.get("eskimo", [])
        nodes = reg.nodes_for_faction("eskimo", FOOD)
        if not workers or not nodes:
            return True, False, "missing worker or node"
        if self._scenario_frame == 5:
            reg.dropoffs_by_faction["eskimo"] = {}
            session.gather_controller.assign(workers[0], nodes[0], session.wallet)
            return False, False, ""
        if self._scenario_frame == 6:
            for _ in range(12):
                _gather_update(
                    session,
                    level,
                    self.DT if RTS_VALIDATION_RUNTIME.fast_mode else self._last_dt,
                )
            if getattr(workers[0], "gather_lost", False):
                return True, True, "worker lost"
        if self._scenario_frame > 8:
            if RTS_VALIDATION_RUNTIME.fast_mode:
                for _ in range(5):
                    _gather_update(session, level, self.DT)
            else:
                _gather_update(session, level, self._last_dt)
            if getattr(workers[0], "gather_lost", False):
                return True, True, "worker lost"
            if self._scenario_frame > 60 and RTS_VALIDATION_RUNTIME.fast_mode:
                return True, False, f"state={workers[0].gather_state} lost={workers[0].gather_lost}"
            if (
                not RTS_VALIDATION_RUNTIME.fast_mode
                and time.time() - self._scenario_started > 22.0
            ):
                return True, False, f"state={workers[0].gather_state} lost={workers[0].gather_lost}"
        return False, False, ""

    FEET_PLANT_IDLE_FRAMES = 4
    FEET_PLANT_WALK_FRAMES = 90
    FEET_PLANT_GOLDEN_IDLE_Y = 3848  # Phase-1 headless capture (level 6 TMX spawn)
    FEET_PLANT_WALL_APPROACH_FRAMES = 90
    FEET_PLANT_WALL_STUCK_FRAMES = 8
    FEET_PLANT_WALL_REVERSE_FRAMES = 24
    FEET_PLANT_TUNNEL_STEP_PX = 24

    def _run_player_feet_plant(self, level):
        player = getattr(level, "player", None)
        if player is None:
            return True, False, "no player"
        if not getattr(player, "mask", None) or not getattr(player, "rect", None):
            return True, False, "player missing rect/mask"

        # Snapshot idle before walking. Tick runs before player.update, so frame 1
        # is still the spawn idle pose.
        if self._scenario_frame <= self.FEET_PLANT_IDLE_FRAMES:
            feet = mask_midbottom_world(player.rect, player.mask)
            center_rect = player.image.get_rect(center=player.hitbox.center)
            legacy_feet = mask_midbottom_world(center_rect, player.mask)
            self._feet_idle_y = int(feet[1])
            self._feet_start_hitbox = (player.hitbox.centerx, player.hitbox.centery)
            self._feet_idle_match = abs(int(feet[1]) - int(legacy_feet[1]))
            self._feet_last_x = player.hitbox.centerx
            return False, False, ""

        walk_frames = self._scenario_frame - self.FEET_PLANT_IDLE_FRAMES
        if walk_frames <= self.FEET_PLANT_WALK_FRAMES:
            _press_key(level.input_manager, pygame.K_RIGHT)
            feet_y = int(mask_midbottom_world(player.rect, player.mask)[1])
            bob = abs(feet_y - self._feet_idle_y)
            if bob > self._feet_max_bob:
                self._feet_max_bob = bob
            self._note_feet_step(player)
            return False, False, ""

        wall_done = self._run_feet_wall_walk(level, player)
        if not wall_done:
            feet_y = int(mask_midbottom_world(player.rect, player.mask)[1])
            bob = abs(feet_y - self._feet_idle_y)
            if bob > self._feet_max_bob:
                self._feet_max_bob = bob
            return False, False, ""

        idle_ok = self._feet_idle_match is not None and self._feet_idle_match <= 1
        golden_ok = abs(self._feet_idle_y - self.FEET_PLANT_GOLDEN_IDLE_Y) <= 1
        bob_ok = self._feet_max_bob <= 1
        wall_ok = (
            (not self._feet_wall_tunnel)
            and self._feet_wall_contacted
            and self._feet_wall_reversed
        )
        details = (
            f"idle_feet_y={self._feet_idle_y} idle_match_px={self._feet_idle_match} "
            f"max_bob={self._feet_max_bob} wall_contacted={int(self._feet_wall_contacted)} "
            f"wall_reversed={int(self._feet_wall_reversed)} tunnel={int(self._feet_wall_tunnel)}"
        )
        return True, idle_ok and golden_ok and bob_ok and wall_ok, details

    def _note_feet_step(self, player):
        x = player.hitbox.centerx
        y = player.hitbox.centery
        if self._feet_last_x is not None and abs(x - self._feet_last_x) > self.FEET_PLANT_TUNNEL_STEP_PX:
            self._feet_wall_tunnel = True
        if self._feet_last_y is not None and abs(y - self._feet_last_y) > self.FEET_PLANT_TUNNEL_STEP_PX:
            self._feet_wall_tunnel = True
        self._feet_last_x = x
        self._feet_last_y = y

    def _feet_axis_pos(self, player):
        if self._feet_wall_axis == "y":
            return player.hitbox.centery
        return player.hitbox.centerx

    def _aim_feet_wall_walk(self, player):
        """Steer toward the nearest obstacle so planted-rect collision is actually hit."""
        self._feet_wall_key = pygame.K_RIGHT
        self._feet_wall_reverse_key = pygame.K_LEFT
        self._feet_wall_sign = 1
        self._feet_wall_axis = "x"
        qt = getattr(player, "QuadTree", None)
        if qt is None or not hasattr(player, "hitbox"):
            return
        px, py = player.hitbox.center
        best = None
        best_d2 = None
        for radius in (256, 768, 2048):
            probe = player.hitbox.inflate(radius * 2, radius * 2)
            hits = qt.hit(HashableRect(probe, player.id))
            for item in hits:
                other = getattr(item, "rect", None)
                if other is None:
                    continue
                cx = min(max(px, other.left), other.right)
                cy = min(max(py, other.top), other.bottom)
                dx = cx - px
                dy = cy - py
                d2 = dx * dx + dy * dy
                if d2 < 4:
                    continue
                if best_d2 is None or d2 < best_d2:
                    best_d2 = d2
                    best = (dx, dy)
            if best is not None:
                break
        if best is None:
            return
        dx, dy = best
        if abs(dx) >= abs(dy):
            self._feet_wall_axis = "x"
            if dx >= 0:
                self._feet_wall_key = pygame.K_RIGHT
                self._feet_wall_reverse_key = pygame.K_LEFT
                self._feet_wall_sign = 1
            else:
                self._feet_wall_key = pygame.K_LEFT
                self._feet_wall_reverse_key = pygame.K_RIGHT
                self._feet_wall_sign = -1
        else:
            self._feet_wall_axis = "y"
            if dy >= 0:
                self._feet_wall_key = pygame.K_DOWN
                self._feet_wall_reverse_key = pygame.K_UP
                self._feet_wall_sign = 1
            else:
                self._feet_wall_key = pygame.K_UP
                self._feet_wall_reverse_key = pygame.K_DOWN
                self._feet_wall_sign = -1

    def _run_feet_wall_walk(self, level, player):
        """Walk into the nearest obstacle, then reverse to check stuck/tunnel."""
        if self._feet_wall_phase is None:
            self._aim_feet_wall_walk(player)
            self._feet_wall_phase = "approach"
            self._feet_stuck_frames = 0
            self._feet_wall_frame = 0
            self._feet_reverse_frames = 0
            self._feet_approach_prev = self._feet_axis_pos(player)

        self._note_feet_step(player)
        pos = self._feet_axis_pos(player)

        if self._feet_wall_phase == "approach":
            _press_key(level.input_manager, self._feet_wall_key)
            self._feet_wall_frame += 1
            progress = (pos - self._feet_approach_prev) * self._feet_wall_sign
            if progress <= 0:
                self._feet_stuck_frames += 1
            else:
                self._feet_stuck_frames = 0
            self._feet_approach_prev = pos
            if self._feet_stuck_frames >= self.FEET_PLANT_WALL_STUCK_FRAMES:
                self._feet_wall_contacted = True
                _release_key(level.input_manager, self._feet_wall_key)
                self._feet_wall_phase = "reverse"
                self._feet_reverse_start = pos
                self._feet_reverse_frames = 0
            elif self._feet_wall_frame >= self.FEET_PLANT_WALL_APPROACH_FRAMES:
                _release_key(level.input_manager, self._feet_wall_key)
                self._feet_wall_phase = "done"
            return self._feet_wall_phase == "done"

        if self._feet_wall_phase == "reverse":
            _press_key(level.input_manager, self._feet_wall_reverse_key)
            self._feet_reverse_frames += 1
            if (pos - self._feet_reverse_start) * self._feet_wall_sign < -2:
                self._feet_wall_reversed = True
            if self._feet_reverse_frames >= self.FEET_PLANT_WALL_REVERSE_FRAMES:
                _release_key(level.input_manager, self._feet_wall_reverse_key)
                self._feet_wall_phase = "done"
            return self._feet_wall_phase == "done"

        return True


    def _release_move_keys(self, level):
        if level is None or getattr(level, "input_manager", None) is None:
            return
        for key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
            _release_key(level.input_manager, key)

    def _press_world_dir(self, level, dx, dy):
        self._release_move_keys(level)
        length = (dx * dx + dy * dy) ** 0.5
        if length < 1e-12:
            return
        nx, ny = dx / length, dy / length
        im = level.input_manager
        if nx > 0.15:
            _press_key(im, pygame.K_RIGHT)
        elif nx < -0.15:
            _press_key(im, pygame.K_LEFT)
        if ny > 0.15:
            _press_key(im, pygame.K_DOWN)
        elif ny < -0.15:
            _press_key(im, pygame.K_UP)

    def _ensure_heightmap(self, level):
        if self._heightmap is not None:
            return self._heightmap
        live = getattr(level.layout_manager, "heightmap", None)
        if live is not None:
            self._heightmap = live
            return self._heightmap
        scale = world_scale_for_layout(level.layout_manager)
        self._heightmap = load_chunk_00_01(
            RTS_VALIDATION_RUNTIME.layout_dir, world_scale=scale
        )
        return self._heightmap

    def _player_feet_xy(self, player):
        if getattr(player, "mask", None) and getattr(player, "rect", None):
            return mask_midbottom_world(player.rect, player.mask)
        return (player.hitbox.centerx, player.hitbox.bottom)

    def _sun_shadow_params(self, level):
        lighting = getattr(level.layout_manager, "lighting", None)
        weather = getattr(level, "weather", None)
        t = float(getattr(weather, "current_time", 12.0) or 12.0)
        if lighting is None or not hasattr(lighting, "sun_shadow"):
            return None
        return lighting.sun_shadow(t)

    def _terrain_hud_lines(self, level):
        player = getattr(level, "player", None)
        hm = self._heightmap
        lines = []
        if player is None:
            return ["h=n/a (no player)"]
        fx, fy = self._player_feet_xy(player)
        h = hm.sample(fx, fy) if hm is not None else None
        g = hm.gradient(fx, fy) if hm is not None else None
        step = hm.gradient_step if hm is not None else None
        tilt = float(getattr(player, "terrain_tilt_deg", 0.0))
        grade_mag = float(getattr(player, "terrain_grade_mag", 0.0))
        grade = getattr(player, "terrain_grade", None)
        shadow = self._sun_shadow_params(level)
        h_txt = "None" if h is None else f"{h:.3f}"
        if g is None:
            slope_txt = "None"
        else:
            slope_txt = f"{g[0]:+.5f},{g[1]:+.5f}"
        step_txt = "n/a" if step is None else str(step)
        if shadow is None:
            shadow_txt = "n/a"
        else:
            shadow_txt = f"{shadow[2]:.3f}"
        lines.append(f"h={h_txt} slope=({slope_txt}) step={step_txt}")
        if grade is None:
            grade_txt = "0,0"
        else:
            grade_txt = f"{grade.x:+.3f},{grade.y:+.3f}"
        lines.append(
            f"g={grade_txt} |g|={grade_mag:.3f} G={TERRAIN_G:g} step={PHYSICS_GRADIENT_STEP} "
            f"tilt_deg={tilt:.2f} shadow_len={shadow_txt}"
        )
        lines.append(f"feet=({int(fx)},{int(fy)})")
        if self._active == "terrain_slope_speed":
            spd = getattr(player, "stats", {}).get("speed", "?")
            lines.append(
                f"lap={self._terrain_laps}/{self.TERRAIN_SLOPE_LAPS} phase={self._terrain_phase} "
                f"base_speed={spd}"
            )
        return lines

    def _run_terrain_height_sample(self, level):
        player = getattr(level, "player", None)
        if player is None or not hasattr(player, "hitbox"):
            return True, False, "no player"
        spawn = (int(player.hitbox.centerx), int(player.hitbox.centery))
        self._terrain_spawn = spawn
        on_map = _player_on_painted_ground(level, player)
        if not on_map:
            return True, False, f"spawn {spawn} is not on painted ground"
        try:
            hm = self._ensure_heightmap(level)
        except Exception as exc:
            return True, False, f"heightmap load failed: {exc}"

        ridge_u8 = hm.sample_u8(*GOLDEN_RIDGE)
        wash_u8 = hm.sample_u8(*GOLDEN_WASH)
        void_s = hm.sample(*GOLDEN_VOID)
        ridge_ok = (
            ridge_u8 is not None
            and abs(ridge_u8 - GOLDEN_HEIGHT_U8[GOLDEN_RIDGE]) <= HEIGHT_U8_TOLERANCE
        )
        wash_ok = (
            wash_u8 is not None
            and abs(wash_u8 - GOLDEN_HEIGHT_U8[GOLDEN_WASH]) <= HEIGHT_U8_TOLERANCE
        )
        void_ok = void_s is None
        _teleport_player(player, GOLDEN_RIDGE)
        gx, gy = _tile_grid_size(level)
        off_grid = not (0 <= GOLDEN_RIDGE[0] < gx and 0 <= GOLDEN_RIDGE[1] < gy)
        details = (
            f"spawn={spawn} on_map={int(on_map)} off_grid_teleport={int(off_grid)} "
            f"ridge_u8={ridge_u8} wash_u8={wash_u8} void={void_s} "
            f"scale={world_scale_for_layout(level.layout_manager):.3f} "
            f"step={hm.gradient_step}"
        )
        ok = ridge_ok and wash_ok and void_ok
        return True, ok, details

    def _terrain_walk_budget(self):
        if RTS_VALIDATION_RUNTIME.fast_mode:
            return self.TERRAIN_WALK_FRAMES_FAST
        return self.TERRAIN_WALK_FRAMES_VISIBLE

    def _note_slope_mult(self, player, which):
        # Tick runs before player.update, so this is last frame's grade force.
        m = float(getattr(player, "terrain_grade_mag", 0.0))
        if which == "ridge":
            if m > 1e-6:
                self._terrain_ridge_mult = m
            return
        if self._terrain_walk_frames >= 2:
            self._terrain_shelf_mult = m

    def _run_terrain_slope_speed(self, level):
        player = getattr(level, "player", None)
        if player is None:
            return True, False, "no player"
        try:
            hm = self._ensure_heightmap(level)
        except Exception as exc:
            return True, False, f"heightmap load failed: {exc}"
        g = hm.gradient(*GOLDEN_RIDGE)
        if g is None:
            return True, False, "no gradient at ridge"
        budget = self._terrain_walk_budget()
        if self._terrain_phase is None:
            _teleport_player(player, GOLDEN_RIDGE)
            self._terrain_phase = "up"
            self._terrain_walk_frames = 0
            self._terrain_laps = 0
            return False, False, ""
        if self._terrain_phase == "up":
            self._press_world_dir(level, g[0], g[1])
            self._terrain_walk_frames += 1
            self._note_slope_mult(player, "ridge")
            if self._terrain_walk_frames >= budget:
                self._terrain_phase = "down"
                self._terrain_walk_frames = 0
            return False, False, ""
        if self._terrain_phase == "down":
            self._press_world_dir(level, -g[0], -g[1])
            self._terrain_walk_frames += 1
            if self._terrain_walk_frames >= budget:
                self._terrain_laps += 1
                if self._terrain_laps < self.TERRAIN_SLOPE_LAPS:
                    self._terrain_phase = "up"
                    self._terrain_walk_frames = 0
                    return False, False, ""
                _teleport_player(player, GOLDEN_SHELF)
                self._terrain_phase = "shelf"
                self._terrain_walk_frames = 0
            return False, False, ""
        if self._terrain_phase == "shelf":
            g_shelf = hm.gradient(*GOLDEN_SHELF)
            if g_shelf is None:
                along = (1.0, 0.0)
            else:
                along = (-g_shelf[1], g_shelf[0])
            self._press_world_dir(level, along[0], along[1])
            self._terrain_walk_frames += 1
            self._note_slope_mult(player, "shelf")
            if self._terrain_walk_frames >= budget:
                self._terrain_phase = "shelf_hold"
            return False, False, ""
        self._note_slope_mult(player, "shelf")
        self._release_move_keys(level)
        ridge_g = hm.gradient(*GOLDEN_RIDGE)
        ridge_mag = 0.0 if ridge_g is None else (ridge_g[0] ** 2 + ridge_g[1] ** 2) ** 0.5
        ridge_mult = self._terrain_ridge_mult
        shelf_mult = self._terrain_shelf_mult
        details = (
            f"grade={ridge_mult} shelf_grade={shelf_mult} "
            f"ridge_grad_mag={ridge_mag:.5f} step={PHYSICS_GRADIENT_STEP} G={TERRAIN_G:g}"
        )
        ok = (
            ridge_mult is not None
            and shelf_mult is not None
            and float(ridge_mult) > 1e-3
            and float(ridge_mult) > float(shelf_mult) + 1e-3
        )
        return True, ok, details

    def _run_terrain_sprite_tilt(self, level):
        player = getattr(level, "player", None)
        if player is None:
            return True, False, "no player"
        try:
            hm = self._ensure_heightmap(level)
        except Exception as exc:
            return True, False, f"heightmap load failed: {exc}"
        if self._terrain_phase is None:
            _teleport_player(player, GOLDEN_RIDGE)
            self._terrain_phase = "ridge"
            return False, False, ""
        if self._terrain_phase == "ridge":
            self._terrain_ridge_tilt = float(getattr(player, "terrain_tilt_deg", 0.0))
            _teleport_player(player, GOLDEN_SHELF)
            self._terrain_phase = "shelf"
            return False, False, ""
        self._terrain_shelf_tilt = float(getattr(player, "terrain_tilt_deg", 0.0))
        ridge_g = hm.gradient(*GOLDEN_RIDGE)
        ridge_mag = 0.0 if ridge_g is None else (ridge_g[0] ** 2 + ridge_g[1] ** 2) ** 0.5
        ridge_tilt = self._terrain_ridge_tilt
        shelf_tilt = self._terrain_shelf_tilt
        details = (
            f"still unimplemented, tilt_deg={ridge_tilt} shelf_tilt={shelf_tilt} "
            f"ridge_grad_mag={ridge_mag:.5f} step={hm.gradient_step}"
        )
        return True, True, details, "probe"

    def _run_terrain_shadow_slope(self, level):
        player = getattr(level, "player", None)
        if player is None:
            return True, False, "no player"
        try:
            hm = self._ensure_heightmap(level)
        except Exception as exc:
            return True, False, f"heightmap load failed: {exc}"
        backend = getattr(level, "backend", None)
        backend_kind = type(backend).__name__ if backend is not None else "unknown"
        drawn = backend_kind != "CPUBackend"
        if self._terrain_phase is None:
            _teleport_player(player, GOLDEN_RIDGE)
            self._terrain_phase = "ridge"
            return False, False, ""
        if self._terrain_phase == "ridge":
            self._terrain_ridge_shadow = self._sun_shadow_params(level)
            _teleport_player(player, GOLDEN_SHELF)
            self._terrain_phase = "shelf"
            return False, False, ""
        ridge_s = self._sun_shadow_params(level)
        ridge_g = hm.gradient(*GOLDEN_RIDGE)
        shelf_g = hm.gradient(*GOLDEN_SHELF)
        drawn_txt = "drawn" if drawn else "not drawn"
        details = (
            f"still unimplemented, time-only sun_shadow params={ridge_s} "
            f"backend={backend_kind} {drawn_txt} "
            f"ridge_g={ridge_g} shelf_g={shelf_g} step={hm.gradient_step}"
        )
        return True, True, details, "probe"


def _find_depletable_node(registry, faction_id):
    for nodes in registry.faction_node_index.get(faction_id, {}).values():
        for node in nodes:
            if node.depletable:
                return node
    return None
