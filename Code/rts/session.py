import logging
import time

import pygame

from game_logging import get_debug_logger

from .actions import RtsActionQueue
from .assets import normalize_faction_id
from .camera import RtsCamera
from .categories import ALL_CATEGORIES, FOOD
from .factions import get_profile
from .input import RtsInput
from .resources import ResourceWallet
from .selection import SelectableRegistry, nearest_sprite_in_direction
from .ui import BuildMenuPanel, ChiefPanel, ResourceBar, RtsPanel, WorkerCommandPanel
from .combat_context import make_rts_combat_context
from .entities import RtsWorkerEntity

_rts_log = get_debug_logger("rts")


class RtsSession:
    INACTIVE = "inactive"
    CAMERA = "camera"
    SELECT = "select"
    PANEL = "panel"
    CHIEF_PANEL = "chief_panel"
    ASSIGN_NODE = "assign_node"
    WORKER_MENU = "worker_menu"
    BUILD_MENU = "build_menu"
    PICK_BUILD_SITE = "pick_build_site"

    CATEGORY_KEYS = (
        pygame.K_1,
        pygame.K_2,
        pygame.K_3,
        pygame.K_4,
        pygame.K_5,
    )

    def __init__(self, world_adapter, input_manager, world_sim):
        self.world = world_adapter
        self.world_sim = world_sim
        self.input = RtsInput(input_manager)
        self.camera = RtsCamera()
        self.selection = SelectableRegistry()
        self.panel = RtsPanel()
        self.chief_panel = ChiefPanel()
        self.worker_command_panel = WorkerCommandPanel()
        self.build_menu_panel = BuildMenuPanel()
        self.resource_bar = ResourceBar()
        self.wallet = ResourceWallet()
        self.queue = RtsActionQueue()
        self.faction = None
        self.state = self.INACTIVE
        self.throne = None
        self.throne_profile_id = ""
        self.pending_workers = []
        self.node_highlight = False
        self.site_highlight = False
        self._worker_menu_worker = None
        self._pick_build_worker = None
        self._pick_building = None
        self._status_message = ""
        self._status_color = (255, 80, 80)
        self._status_until = 0.0

    @property
    def gather_controller(self):
        return self.world_sim.gather_controller

    @property
    def food_upkeep(self):
        return self.world_sim.food_upkeep_for(self._active_faction_id())

    def is_active(self):
        return self.state != self.INACTIVE

    def enter(self, throne=None):
        self.throne = throne
        self.throne_profile_id = str(getattr(throne, "profile_id", "")).strip()
        focus = throne or self.world.get_player()
        self.camera.snap_to(focus)
        self.state = self.CAMERA
        self.pending_workers = []
        self._load_faction_from_throne(throne)
        if self._active_faction_id():
            sim_wallet = self.world_sim.get_wallet(self._active_faction_id())
            if sim_wallet is not None:
                self.wallet = sim_wallet
        self.wallet.reset_rates()
        registry = self.world.get_rts_registry()
        self.gather_controller.registry = registry
        self.world_sim.build_controller.registry = registry
        self.refresh_selectables()
        fid = self._active_faction_id() or "none"
        _rts_log.debug(
            "enter throne=%s faction=%s wallet_id=%s state=%s",
            self.throne_profile_id,
            fid,
            id(self.wallet),
            self.state,
        )

    def _load_faction_from_throne(self, throne):
        self.faction = None
        faction_id = ""
        if throne is not None:
            env = getattr(throne, "env_config", None) or {}
            faction_id = normalize_faction_id(env.get("rts_faction_id", ""))
        if faction_id:
            self.faction = get_profile(faction_id)
        if self.faction is not None:
            self.wallet = self.world_sim.get_wallet(self.faction.id)
        else:
            self.wallet = ResourceWallet()

    def exit(self, request_stand=True):
        _rts_log.debug("exit rts request_stand=%s", request_stand)
        if request_stand:
            self.world.request_player_stand()
        self.chief_panel.close()
        self.state = self.INACTIVE
        self.selection.selected = None
        self.throne = None
        self.faction = None
        self.pending_workers = []

    def refresh_selectables(self):
        sprites = self.world.get_selectable_sprites(self.throne_profile_id)
        if self.state == self.PICK_BUILD_SITE:
            sprites = self._filter_build_site_sprites(sprites)
        self.selection.rebuild(sprites)

    def camera_focus(self):
        if self.is_active():
            return self.camera
        return self.world.get_player()

    def camera_rect(self):
        surface = self.world.get_display_surface()
        if surface is None:
            return None
        width, height = surface.get_size()
        return pygame.Rect(
            self.camera.rect.centerx - width // 2,
            self.camera.rect.centery - height // 2,
            width,
            height,
        )

    def update(self, dt):
        if not self.is_active():
            return
        if self.world.is_player_dead():
            self.state = self.INACTIVE
            return

        self.refresh_selectables()
        self.queue.update(dt)

        if self.input.pressed_exit():
            self.exit(request_stand=True)
            return
        if self.input.pressed_snap():
            self.snap_to_throne()

        if self.state == self.CAMERA:
            self._update_camera_mode(dt)
        elif self.state == self.SELECT:
            self._update_select_mode(dt)
        elif self.state == self.PANEL:
            self._update_panel_mode(dt)
        elif self.state == self.CHIEF_PANEL:
            self.chief_panel.handle_input(self)
        elif self.state == self.ASSIGN_NODE:
            self._update_assign_node_mode(dt)
        elif self.state == self.WORKER_MENU:
            self.worker_command_panel.handle_input(self)
        elif self.state == self.BUILD_MENU:
            self.build_menu_panel.handle_input(self)
        elif self.state == self.PICK_BUILD_SITE:
            self._update_pick_build_site_mode(dt)

    def _active_faction_id(self):
        if self.faction is not None:
            return self.faction.id
        return ""

    def _update_camera_mode(self, dt):
        self.camera.move(self.input.move_direction(), dt, self.world.get_map_bounds())
        if self.input.pressed_tab():
            self.state = self.SELECT
            self.selection.select_bottom_left(self.camera_rect())

    def _update_select_mode(self, dt):
        self.node_highlight = bool(self.pending_workers)
        self._set_node_highlights(self.node_highlight)

        direction = self.input.just_pressed_direction()
        if direction.length_squared() > 0:
            self.selection.move_selection(direction, self.camera_rect())

        sel = self.selection.selected
        if sel is not None:
            kind = str(getattr(sel.sprite, "kind", "")).strip().lower()
            if kind == "rts_unit":
                if sel.sprite not in self.pending_workers:
                    self.pending_workers = [sel.sprite]
            elif kind == "chief":
                self.pending_workers = []

        if self.input.input_manager.is_key_just_pressed(pygame.K_g):
            self.state = self.ASSIGN_NODE
            return

        for i, key in enumerate(self.CATEGORY_KEYS):
            if self.input.input_manager.is_key_just_pressed(key):
                if i < len(ALL_CATEGORIES):
                    cat = ALL_CATEGORIES[i]
                    _rts_log.debug(
                        "key %d -> nearest %s state=%s pending=%d selected=%s",
                        i + 1,
                        cat,
                        self.state,
                        len(self.pending_workers),
                        getattr(sel, "kind", None) if sel else None,
                    )
                    self._assign_nearest_category(cat)
                return

        if self.input.pressed_confirm():
            if self._try_open_chief(sel):
                return
            if self._try_assign_to_selected_node():
                return
            if sel is not None and str(getattr(sel.sprite, "kind", "")) == "rts_unit":
                self._open_worker_menu(sel.sprite)
                return
            if sel is not None:
                self.state = self.PANEL
        elif self.input.pressed_cancel() or self.input.pressed_tab():
            self.pending_workers = []
            self.node_highlight = False
            self._set_node_highlights(False)
            self.state = self.CAMERA
            self.selection.selected = None

    def _update_assign_node_mode(self, dt):
        self.node_highlight = True
        self._set_node_highlights(True)
        direction = self.input.just_pressed_direction()
        if direction.length_squared() > 0:
            self._move_selection_among_nodes(direction)
        if self.input.pressed_confirm():
            self._try_assign_to_selected_node()
            self.state = self.SELECT
        elif self.input.pressed_cancel():
            self.state = self.SELECT

    def _move_selection_among_nodes(self, direction):
        registry = self.world.get_rts_registry()
        fid = self._active_faction_id()
        nodes = registry.nodes_for_faction(fid)
        if not nodes:
            return
        if self.selection.selected is None:
            self.selection.selected = self.selection._wrap(nodes[0])
            return
        current = self.selection.selected.sprite
        try:
            idx = next(i for i, n in enumerate(nodes) if n is current)
        except StopIteration:
            idx = 0
        if direction.x > 0:
            idx = (idx + 1) % len(nodes)
        elif direction.x < 0:
            idx = (idx - 1) % len(nodes)
        elif direction.y > 0:
            idx = (idx + 1) % len(nodes)
        elif direction.y < 0:
            idx = (idx - 1) % len(nodes)
        self.selection.selected = self.selection._wrap(nodes[idx])

    def _try_open_chief(self, sel):
        if sel is None or str(getattr(sel.sprite, "kind", "")) != "chief":
            return False
        registry = self.world.get_rts_registry()
        chief = registry.get_chief_for_throne(self.throne_profile_id)
        if chief is None or sel.sprite is not chief:
            return False
        self.chief_panel.open(chief)
        self.state = self.CHIEF_PANEL
        return True

    def _try_assign_to_selected_node(self):
        sel = self.selection.selected
        if sel is None or str(getattr(sel.sprite, "kind", "")) != "resource_node":
            if sel is not None:
                _rts_log.debug(
                    "assign_node skipped: selected kind=%s (need resource_node)",
                    getattr(sel.sprite, "kind", ""),
                )
            return False
        node = sel.sprite
        workers = list(self.pending_workers)
        if not workers and sel.sprite and getattr(sel.sprite, "kind", "") == "rts_unit":
            workers = [sel.sprite]
        if not workers:
            _rts_log.warning("assign_node: no pending_workers for node=%s", node.node_kind)
            return False
        wallet = self.world_sim.get_wallet(self._active_faction_id())
        for worker in workers:
            self.world_sim.assign_gather(worker, node, wallet)
        _rts_log.debug("assign_node ok node=%s workers=%d", node.node_kind, len(workers))
        self.pending_workers = []
        self.node_highlight = False
        self._set_node_highlights(False)
        return True

    def _assign_nearest_category(self, category):
        registry = self.world.get_rts_registry()
        fid = self._active_faction_id()
        workers = self.pending_workers
        if not workers:
            _rts_log.warning(
                "assign_nearest %s: no pending_workers (arrow onto worker first)",
                category,
            )
            return
        if not fid:
            _rts_log.warning(
                "assign_nearest %s: no faction (throne missing rts_faction_id?)", category
            )
            return
        all_nodes = registry.nodes_for_faction(fid, category) if registry else []
        wallet = self.world_sim.get_wallet(fid)
        for worker in workers:
            from_pos = worker.rect.center
            node = registry.nearest_node_with_slot(fid, category, from_pos)
            if node is not None:
                self.gather_controller.assign(worker, node, wallet)
            else:
                _rts_log.warning(
                    "assign_nearest %s: no node with slot faction=%s worker@%s "
                    "nodes_for_faction=%d",
                    category,
                    fid,
                    from_pos,
                    len(all_nodes),
                )

    def spawn_worker_from_chief(self, chief):
        if chief.population_idle <= 0:
            _rts_log.warning(
                "spawn_worker blocked: no idle pop (total=%s workers=%s)",
                chief.population_total,
                chief.population_workers,
            )
            return
        offset = (len(chief.spawned_workers) * 24, 0)
        pos = (
            chief.rect.centerx + offset[0],
            chief.rect.centery + 40 + offset[1],
        )
        layout_cb = None
        if hasattr(self.world, "get_layout_callback_update_quad_tree"):
            layout_cb = self.world.get_layout_callback_update_quad_tree()
        groups = self.world.get_sprite_groups()
        obstacles = self.world.get_obstacle_sprites()
        combat_context = make_rts_combat_context(self.world)
        worker = RtsWorkerEntity(
            pos,
            groups,
            chief.faction_id,
            chief.worker_sprite_key,
            chief,
            obstacle_sprites=obstacles,
            combat_context=combat_context,
            layout_callback_update_quad_tree=layout_cb,
            world_sim=self.world_sim,
        )
        if layout_cb is not None:
            from hashRect import HashableRect

            layout_cb(
                obstacle_sprite=HashableRect(worker.rect, worker.id),
                alive=True,
                remove_existing=False,
            )
        registry = self.world.get_rts_registry()
        registry.register_worker(worker)
        chief.add_worker_pop(worker)
        _rts_log.debug(
            "spawn_worker @%s faction=%s idle_left=%s registry_count=%s",
            pos,
            chief.faction_id,
            chief.population_idle,
            len(registry.workers_by_faction.get(chief.faction_id, [])),
        )

    def despawn_worker_from_chief(self, chief):
        worker = chief.remove_idle_worker()
        if worker is None:
            return
        self.world_sim.cancel_worker_jobs(worker)
        registry = self.world.get_rts_registry()
        registry.unregister_worker(worker)
        layout_cb = None
        if hasattr(self.world, "get_layout_callback_update_quad_tree"):
            layout_cb = self.world.get_layout_callback_update_quad_tree()
        if layout_cb is not None and hasattr(worker, "id"):
            from hashRect import HashableRect

            layout_cb(
                obstacle_sprite=HashableRect(worker.rect, worker.id),
                remove_existing=True,
                alive=False,
            )
        worker.kill()

    def select_all_workers(self, faction_id):
        registry = self.world.get_rts_registry()
        fid = normalize_faction_id(faction_id)
        self.pending_workers = list(registry.workers_by_faction.get(fid, []))

    def _set_node_highlights(self, on):
        registry = self.world.get_rts_registry()
        fid = self._active_faction_id()
        for node in registry.nodes_for_faction(fid):
            node.highlighted = on

    def _set_site_highlights(self, on):
        registry = self.world.get_rts_registry()
        if registry is None:
            return
        building = self._pick_building
        worker = self._pick_build_worker
        fid = getattr(worker, "faction_id", "") if worker is not None else self._active_faction_id()
        req = building.placement_requires if building is not None else None
        for site in registry.build_sites_for_faction(fid, requires=req, available_only=True):
            site.highlighted = on

    def _filter_build_site_sprites(self, sprites):
        building = self._pick_building
        worker = self._pick_build_worker
        if building is None or worker is None:
            return [s for s in sprites if str(getattr(s, "kind", "")) != "build_site"]
        fid = worker.faction_id
        req = building.placement_requires
        filtered = []
        for sprite in sprites:
            kind = str(getattr(sprite, "kind", "")).strip().lower()
            if kind != "build_site":
                filtered.append(sprite)
                continue
            if (
                getattr(sprite, "faction_id", "") == fid
                and sprite.is_available()
                and getattr(sprite, "requires", "") == req
            ):
                filtered.append(sprite)
        return filtered

    def _open_worker_menu(self, worker):
        self._worker_menu_worker = worker
        self.worker_command_panel.open(worker)
        self.build_menu_panel.close()
        self.state = self.WORKER_MENU
        self.pending_workers = []
        self.node_highlight = False
        self._set_node_highlights(False)

    def _open_build_menu(self, worker):
        self.worker_command_panel.close()
        self._worker_menu_worker = worker
        wallet = self.world_sim.get_wallet(self._active_faction_id())
        self.build_menu_panel.open(worker, self._active_faction_id(), wallet)
        self.state = self.BUILD_MENU

    def _open_pick_build_site(self, worker, building):
        registry = self.world.get_rts_registry()
        sites = registry.build_sites_for_faction(
            worker.faction_id,
            requires=building.placement_requires,
            available_only=True,
        )
        if not sites:
            self._flash_message("No build site")
            return

        self.build_menu_panel.close()
        self._pick_build_worker = worker
        self._pick_building = building
        self.state = self.PICK_BUILD_SITE
        self.site_highlight = True
        self._set_site_highlights(True)
        self.refresh_selectables()
        site = registry.nearest_unbuilt_site(
            worker.faction_id,
            building.placement_requires,
            worker.rect.center,
        )
        if site is not None:
            self._select_build_site_sprite(site)
            self._snap_camera_to_target(site)

    def _select_build_site_sprite(self, site):
        for selectable in self.selection.selectables:
            if selectable.sprite is site:
                self.selection.selected = selectable
                return
        self.selection.selected = self.selection._wrap(site)

    def _update_pick_build_site_mode(self, dt):
        self.site_highlight = True
        self._set_site_highlights(True)
        direction = self.input.just_pressed_direction()
        if direction.length_squared() > 0:
            self._move_selection_among_sites(direction)
        if self.input.pressed_confirm():
            self._try_assign_build_at_site()
        elif self.input.pressed_cancel():
            self.site_highlight = False
            self._set_site_highlights(False)
            self.build_menu_panel.open(
                self._pick_build_worker,
                self._active_faction_id(),
                self.world_sim.get_wallet(self._active_faction_id()),
            )
            self.state = self.BUILD_MENU

    def _move_selection_among_sites(self, direction):
        registry = self.world.get_rts_registry()
        worker = self._pick_build_worker
        building = self._pick_building
        if worker is None or building is None:
            return
        sites = registry.build_sites_for_faction(
            worker.faction_id,
            requires=building.placement_requires,
            available_only=True,
        )
        if not sites:
            return
        current = self.selection.selected.sprite if self.selection.selected else None
        if current is None:
            site = registry.nearest_unbuilt_site(
                worker.faction_id,
                building.placement_requires,
                worker.rect.center,
            )
            if site is None:
                return
            self._select_build_site_sprite(site)
            self._snap_camera_to_target(site)
            return
        origin = current.rect.center
        next_site = nearest_sprite_in_direction(origin, sites, direction, current=current)
        if next_site is None or next_site is current:
            return
        self.selection.selected = self.selection._wrap(next_site)
        self._snap_camera_to_target(next_site)

    def _flash_message(self, text, color=(255, 80, 80), duration_sec=2.0):
        self._status_message = str(text)
        self._status_color = color
        self._status_until = time.monotonic() + float(duration_sec)

    def _snap_camera_to_target(self, target):
        self.camera.snap_to(target)
        self.camera.clamp(self.world.get_map_bounds())

    def _try_assign_build_at_site(self):
        sel = self.selection.selected
        worker = self._pick_build_worker
        building = self._pick_building
        if sel is None or worker is None or building is None:
            _rts_log.debug(
                "assign_build_at_site skipped: sel=%s worker=%s building=%s",
                sel is not None,
                worker is not None,
                building is not None,
            )
            return False
        sel_kind = str(getattr(sel.sprite, "kind", "")).strip().lower()
        if sel_kind != "build_site":
            _rts_log.debug(
                "assign_build_at_site skipped: selected kind=%s (need build_site)",
                sel_kind,
            )
            return False
        site = sel.sprite
        wallet = self.world_sim.get_wallet(self._active_faction_id())
        _rts_log.debug(
            "assign_build_at_site confirm worker@%s site@%s building=%s site_state=%s",
            worker.rect.center,
            site.build_center,
            building.id,
            getattr(site, "state", "?"),
        )
        ok = self.world_sim.assign_build(
            worker, site, building.id, wallet=wallet, world_adapter=self.world
        )
        if ok:
            _rts_log.debug(
                "assign_build_at_site ok worker@%s -> site@%s",
                worker.rect.center,
                site.build_center,
            )
            self.site_highlight = False
            self._set_site_highlights(False)
            self._pick_build_worker = None
            self._pick_building = None
            self.state = self.SELECT
        else:
            _rts_log.warning(
                "assign_build_at_site failed worker@%s site@%s building=%s site_state=%s",
                worker.rect.center,
                site.build_center,
                building.id,
                getattr(site, "state", "?"),
            )
            self._flash_message("Build assign failed")
        return ok

    def _update_panel_mode(self, dt):
        if self.input.pressed_cancel() or self.input.pressed_tab():
            self.state = self.SELECT

    def snap_to_throne(self):
        self.camera.snap_to(self.throne or self.world.get_player())
        self.camera.clamp(self.world.get_map_bounds())

    def draw(self):
        if not self.is_active():
            return
        surface = self.world.get_display_surface()
        if surface is None:
            return
        offset = self._camera_offset(surface)
        self._draw_node_highlights(surface, offset)
        self._draw_site_highlights(surface, offset)
        self.resource_bar.draw(
            surface,
            self.wallet,
            self.faction,
            low_food=self.world_sim.low_food_for_faction(self._active_faction_id()),
        )
        if self.state != self.CHIEF_PANEL:
            self.panel.draw_highlight(surface, self.selection.selected, offset)
        if self.state == self.PANEL:
            self.panel.draw(
                surface,
                self.selection.selected,
                self.wallet.to_legacy(),
                self.queue,
            )
        if self.state == self.CHIEF_PANEL:
            self.chief_panel.draw(surface)
        if self.state == self.WORKER_MENU:
            self.worker_command_panel.draw(surface, self.wallet)
        if self.state == self.BUILD_MENU:
            self.build_menu_panel.draw(surface)
        self._draw_mode_hint(surface)
        if _rts_log.isEnabledFor(logging.DEBUG):
            self._draw_debug_overlay(surface)

    def _draw_debug_overlay(self, surface):
        font = pygame.font.Font(None, 22)
        y = 96
        fid = self._active_faction_id() or "none"
        lines = [
            f"RTS dbg mode={self.state} faction={fid}",
            f"pending_workers={len(self.pending_workers)} "
            f"wallet_food={self.wallet.get(FOOD)} wallet_id={id(self.wallet)}",
        ]
        tasks = list(self.gather_controller.tasks.values())
        if tasks:
            for w in tasks[:4]:
                lines.append(
                    f"  worker@{w.rect.center} state={w.gather_state} lost={w.gather_lost}"
                )
        else:
            lines.append("  (no gather tasks)")
        for line in lines:
            surf = font.render(line, True, (120, 255, 160))
            surface.blit(surf, (16, y))
            y += 20

    def _draw_node_highlights(self, surface, offset):
        registry = self.world.get_rts_registry()
        fid = self._active_faction_id()
        for node in registry.nodes_for_faction(fid):
            if not getattr(node, "highlighted", False):
                continue
            rect = node.rect.move(-offset.x, -offset.y)
            pygame.draw.rect(surface, (255, 220, 80), rect.inflate(6, 6), 2)

    def _draw_site_highlights(self, surface, offset):
        if not self.site_highlight:
            return
        registry = self.world.get_rts_registry()
        if registry is None:
            return
        building = self._pick_building
        worker = self._pick_build_worker
        fid = getattr(worker, "faction_id", "") if worker is not None else self._active_faction_id()
        req = building.placement_requires if building is not None else None
        for site in registry.build_sites_for_faction(fid, requires=req, available_only=True):
            if not getattr(site, "highlighted", False):
                continue
            rect = site.rect.move(-offset.x, -offset.y)
            pygame.draw.rect(surface, (120, 200, 255), rect.inflate(8, 8), 2)

    def _camera_offset(self, surface):
        width, height = surface.get_size()
        return pygame.math.Vector2(
            self.camera.rect.centerx - width // 2,
            self.camera.rect.centery - height // 2,
        )

    def _draw_mode_hint(self, surface):
        font = pygame.font.Font(None, 24)
        if self._status_message and time.monotonic() < self._status_until:
            rendered = font.render(self._status_message, True, self._status_color)
            surface.blit(rendered, (16, 72))
            return
        hints = {
            self.CAMERA: "Arrows move | Tab select | Home snap | Space stand",
            self.SELECT: "Worker Enter=menu | node Enter=gather | G assign | 1-5 cat | Tab back",
            self.ASSIGN_NODE: "Pick node Enter | Esc back",
            self.WORKER_MENU: "Gather / Build / Stop | Esc back",
            self.BUILD_MENU: "Pick building Enter | Esc back",
            self.PICK_BUILD_SITE: "Pick site Enter | Esc back",
            self.CHIEF_PANEL: "Chief panel active",
            self.PANEL: "Esc back | Space stand",
        }
        text = hints.get(self.state, "")
        rendered = font.render(text, True, (240, 240, 220))
        surface.blit(rendered, (16, 72))
