import time

import pygame

from game_logging import get_debug_logger
from navigation.grid_pathfinder import find_path
from navigation.quad_mover import step_toward

from ..entities.worker import (
    DELIVERING,
    GATHERING,
    IDLE,
    LOST,
    MOVING_TO_DROPOFF,
    MOVING_TO_NODE,
    WAITING_AT_NODE,
)

_rts_log = get_debug_logger("rts")
_MOVE_LOG_INTERVAL = 0.5
_GATHER_REACH_RADIUS = 14.0
_STUCK_REPLAN_SECONDS = 2.0


class GatherController:
    def __init__(self, registry=None):
        self.registry = registry
        self.tasks = {}
        self._wallet = None
        self._wallet_resolver = None
        self._last_logged_state = {}
        self._move_log_next = {}
        self._walk_grid = None
        self._obstacle_quad_tree = None
        self._stuck_check = {}

    def set_wallet(self, wallet):
        self._wallet = wallet

    def set_wallet_resolver(self, resolver):
        """Callable(faction_id) -> ResourceWallet for per-faction delivery."""
        self._wallet_resolver = resolver

    def _wallet_for_worker(self, worker):
        if self._wallet_resolver is not None and worker is not None:
            fid = getattr(worker, "faction_id", "")
            wallet = self._wallet_resolver(fid)
            if wallet is not None:
                return wallet
        return self._wallet

    def set_navigation(self, walk_grid=None, obstacle_quad_tree=None):
        if walk_grid is not None:
            self._walk_grid = walk_grid
        if obstacle_quad_tree is not None:
            self._obstacle_quad_tree = obstacle_quad_tree

    def assign(self, worker, node, wallet=None):
        if worker is None or node is None:
            _rts_log.debug("assign rejected: worker=%s node=%s", worker, node)
            return False
        if not node.is_active():
            _rts_log.debug(
                "assign rejected: node inactive kind=%s", getattr(node, "node_kind", "")
            )
            return False
        if wallet is not None:
            self._wallet = wallet
        dropoff = None
        if self.registry is not None:
            dropoff = self.registry.find_dropoff(worker.faction_id, node.dropoff_kind)
        worker.assigned_node = node
        worker.assigned_dropoff = dropoff
        worker.gather_lost = False
        worker.gather_state = MOVING_TO_NODE
        worker._registered = False
        worker._timer = 0.0
        worker._delivery_category = node.resource_category
        worker._delivery_amount = node.yield_amount
        worker._dropoff_path_planned = False
        worker._path = []
        worker._path_index = 0
        self.tasks[id(worker)] = worker
        self._move_log_next.pop(id(worker), None)
        self._stuck_check.pop(id(worker), None)
        self._log_state(worker, "assign")
        _rts_log.debug(
            "assign ok worker@%s faction=%s -> node=%s cat=%s dropoff=%s wallet_id=%s",
            worker.rect.center,
            worker.faction_id,
            getattr(node, "node_kind", "?"),
            node.resource_category,
            getattr(dropoff, "dropoff_kind", None) if dropoff else "MISSING",
            id(self._wallet),
        )
        if dropoff is None:
            _rts_log.warning(
                "assign: no dropoff for faction=%s dropoff_kind=%s (worker will LOST on update)",
                worker.faction_id,
                node.dropoff_kind,
            )
        elif self._walk_grid is not None and not self._plan_path_to(
            worker, node.gather_point, "assign"
        ):
            worker.gather_state = LOST
            worker.gather_lost = True
            _rts_log.warning(
                "assign: no path to node %s from %s",
                node.gather_point,
                worker.rect.center,
            )
        return True

    def cancel(self, worker):
        if worker is None:
            return
        if getattr(worker, "_registered", False) and worker.assigned_node is not None:
            worker.assigned_node.unregister_worker()
        worker.assigned_node = None
        worker.assigned_dropoff = None
        worker.gather_state = IDLE
        worker._registered = False
        worker._path = []
        worker._path_index = 0
        worker._dropoff_path_planned = False
        self.tasks.pop(id(worker), None)
        self._last_logged_state.pop(id(worker), None)
        self._stuck_check.pop(id(worker), None)
        _rts_log.debug(
            "gather cancel worker@%s", getattr(worker, "rect", None) and worker.rect.center
        )

    def update(self, dt, obstacle_sprites=None, wallet=None, walk_grid=None, obstacle_quad_tree=None):
        if wallet is not None:
            self._wallet = wallet
        if walk_grid is not None:
            self._walk_grid = walk_grid
        if obstacle_quad_tree is not None:
            self._obstacle_quad_tree = obstacle_quad_tree
        for worker in list(self.tasks.values()):
            self._step_worker(worker, float(dt or 0), obstacle_sprites)

    def _log_state(self, worker, reason=""):
        wid = id(worker)
        state = getattr(worker, "gather_state", "?")
        prev = self._last_logged_state.get(wid)
        if prev == state and reason not in ("assign", "deliver", "lost"):
            return
        self._last_logged_state[wid] = state
        _rts_log.debug(
            "gather state=%s worker@%s reason=%s lost=%s",
            state,
            worker.rect.center,
            reason,
            getattr(worker, "gather_lost", False),
        )

    def _plan_path_to(self, worker, goal_px, reason=""):
        grid = self._walk_grid
        if grid is None:
            worker._path = []
            worker._path_index = 0
            return True
        path = find_path(grid, worker.rect.center, goal_px)
        if not path:
            worker._path = []
            worker._path_index = 0
            _rts_log.warning(
                "path failed worker@%s -> %s reason=%s",
                worker.rect.center,
                goal_px,
                reason,
            )
            return False
        path[-1] = pygame.math.Vector2(goal_px[0], goal_px[1])
        worker._path = path
        worker._path_index = 0
        self._stuck_check[id(worker)] = (time.monotonic(), pygame.math.Vector2(worker.rect.center))
        _rts_log.debug(
            "path plan %d waypoints worker@%s -> %s reason=%s",
            len(path),
            worker.rect.center,
            goal_px,
            reason,
        )
        return True

    def _skip_sprites(self, unit):
        skip = [unit]
        node = getattr(unit, "assigned_node", None)
        dropoff = getattr(unit, "assigned_dropoff", None)
        if node is not None:
            skip.append(node)
        if dropoff is not None:
            skip.append(dropoff)
        return skip

    def _step_worker(self, worker, dt, obstacle_sprites):
        node = worker.assigned_node
        dropoff = worker.assigned_dropoff
        state = worker.gather_state

        if state == LOST:
            return

        if dropoff is None:
            worker.gather_state = LOST
            worker.gather_lost = True
            self._log_state(worker, "no_dropoff")
            _rts_log.warning(
                "gather LOST: no dropoff faction=%s node=%s",
                worker.faction_id,
                getattr(node, "dropoff_kind", ""),
            )
            return

        if state == MOVING_TO_NODE:
            if not worker._registered:
                if node.has_free_slot():
                    node.register_worker()
                    worker._registered = True
                else:
                    worker.gather_state = WAITING_AT_NODE
                    return
            if self._move_along_path(
                worker, node.gather_point, dt, obstacle_sprites, label="to_node"
            ):
                worker.gather_state = GATHERING
                worker._timer = node.gather_duration
                self._log_state(worker, "at_node")
            return

        if state == WAITING_AT_NODE:
            if node.has_free_slot():
                node.register_worker()
                worker._registered = True
                worker.gather_state = MOVING_TO_NODE
                if self._walk_grid is not None:
                    self._plan_path_to(worker, node.gather_point, "slot_open")
            return

        if state == GATHERING:
            worker._timer -= dt
            if worker._timer <= 0:
                node.complete_gather_cycle()
                if worker._registered:
                    node.unregister_worker()
                    worker._registered = False
                worker.gather_state = MOVING_TO_DROPOFF
                worker._dropoff_path_planned = False
                self._log_state(worker, "gather_done")
            return

        if state == MOVING_TO_DROPOFF:
            if not worker._dropoff_path_planned:
                worker._dropoff_path_planned = True
                if self._walk_grid is not None and not self._plan_path_to(
                    worker, dropoff.rect.center, "to_dropoff"
                ):
                    worker.gather_state = LOST
                    worker.gather_lost = True
                    self._log_state(worker, "path_failed_dropoff")
                    return
            if self._move_along_path(
                worker, dropoff.rect.center, dt, obstacle_sprites, label="to_dropoff"
            ):
                worker.gather_state = DELIVERING
                worker._timer = 0.25
                self._log_state(worker, "at_dropoff")
            return

        if state == DELIVERING:
            worker._timer -= dt
            if worker._timer > 0:
                return
            if not dropoff.accepts(worker._delivery_category):
                worker.gather_state = LOST
                worker.gather_lost = True
                self._log_state(worker, "dropoff_reject")
                _rts_log.warning(
                    "gather LOST: dropoff %s rejects %s",
                    dropoff.dropoff_kind,
                    worker._delivery_category,
                )
                return
            wallet = self._wallet_for_worker(worker)
            if wallet is not None:
                before = wallet.get(worker._delivery_category)
                wallet.add(worker._delivery_category, worker._delivery_amount)
                after = wallet.get(worker._delivery_category)
                _rts_log.debug(
                    "deliver %s +%s wallet %s->%s (wallet_id=%s)",
                    worker._delivery_category,
                    worker._delivery_amount,
                    before,
                    after,
                    id(wallet),
                )
                self._log_state(worker, "deliver")
            if node is None or not node.is_active():
                worker.gather_state = LOST
                return
            worker._dropoff_path_planned = False
            if node.has_free_slot():
                node.register_worker()
                worker._registered = True
                worker.gather_state = MOVING_TO_NODE
                if self._walk_grid is not None:
                    self._plan_path_to(worker, node.gather_point, "loop")
            else:
                worker.gather_state = WAITING_AT_NODE

    def _move_along_path(self, unit, final_goal, dt, obstacle_sprites, label=""):
        path = getattr(unit, "_path", None) or []
        idx = int(getattr(unit, "_path_index", 0))
        on_last = path and idx >= len(path) - 1
        if path and idx < len(path) and not on_last:
            target = (int(path[idx].x), int(path[idx].y))
        elif on_last and final_goal is not None:
            target = final_goal
        elif path and idx < len(path):
            target = (int(path[idx].x), int(path[idx].y))
        else:
            target = final_goal

        arrived = self._step_toward_target(
            unit, target, dt, obstacle_sprites, label, final_goal=final_goal
        )
        if not arrived:
            self._maybe_replan_stuck(unit, final_goal, label)
            return False

        if path and idx < len(path) - 1:
            unit._path_index = idx + 1
            if self._should_log_move(unit, f"{label}_waypoint", interval=1.0):
                _rts_log.debug(
                    "waypoint advance %d/%d worker@%s",
                    idx + 1,
                    len(path),
                    unit.rect.center,
                )
            self._stuck_check[id(unit)] = (
                time.monotonic(),
                pygame.math.Vector2(unit.rect.center),
            )
            return False
        return True

    def _maybe_replan_stuck(self, unit, goal_px, label):
        if self._walk_grid is None:
            return
        wid = id(unit)
        now = time.monotonic()
        pos = pygame.math.Vector2(unit.rect.center)
        entry = self._stuck_check.get(wid)
        if entry is None:
            self._stuck_check[wid] = (now, pos)
            return
        since, last_pos = entry
        if pos.distance_to(last_pos) > 4.0:
            self._stuck_check[wid] = (now, pos)
            return
        if now - since < _STUCK_REPLAN_SECONDS:
            return
        _rts_log.debug("path replan worker@%s reason=stuck label=%s", unit.rect.center, label)
        if self._plan_path_to(unit, goal_px, f"replan_{label}"):
            self._stuck_check[wid] = (now, pos)

    def _step_toward_target(self, unit, target, dt, obstacle_sprites, label, final_goal=None):
        if self._obstacle_quad_tree is not None:
            speed = float(getattr(unit, "speed", 120.0))
            skip = self._skip_sprites(unit)
            old = unit.rect.center
            arrived = step_toward(
                unit.rect,
                target,
                dt,
                speed,
                self._obstacle_quad_tree,
                skip_sprites=skip,
                reach=_GATHER_REACH_RADIUS,
            )
            if unit.rect.center != old and self._should_log_move(unit, f"{label}_ok", interval=1.0):
                _rts_log.debug(
                    "move %s OK worker@%s -> %s",
                    label,
                    old,
                    unit.rect.center,
                )
            if arrived and self._should_log_move(unit, f"{label}_arrived", interval=1.0):
                _rts_log.debug(
                    "move %s ARRIVED worker@%s goal=%s",
                    label,
                    unit.rect.center,
                    target,
                )
            return arrived

        return self._move_toward(unit, target, dt, obstacle_sprites, label=label)

    def _should_log_move(self, unit, key, interval=_MOVE_LOG_INTERVAL):
        wid = id(unit)
        now = time.monotonic()
        bucket = self._move_log_next.setdefault(wid, {})
        if now < bucket.get(key, 0.0):
            return False
        bucket[key] = now + interval
        return True

    def _collision_hits(self, unit, obstacle_sprites):
        """Collide against obstacles but never the unit or its gather targets."""
        if obstacle_sprites is None:
            return []
        skip = set(self._skip_sprites(unit))
        hits = []
        for sprite in obstacle_sprites:
            if sprite in skip:
                continue
            if unit.rect.colliderect(sprite.rect):
                hits.append(sprite)
        return hits

    def _hit_summary(self, unit, hits):
        parts = []
        for sprite in hits[:8]:
            if sprite is unit:
                parts.append("self")
                continue
            kind = str(getattr(sprite, "kind", "") or type(sprite).__name__)
            center = getattr(sprite, "rect", None) and sprite.rect.center
            parts.append(f"{kind}@{center}")
        if len(hits) > 8:
            parts.append(f"+{len(hits) - 8}")
        return ", ".join(parts) if parts else "none"

    def _move_toward(self, unit, target, dt, obstacle_sprites, label=""):
        pos = pygame.math.Vector2(unit.rect.center)
        goal = pygame.math.Vector2(target)
        delta = goal - pos
        dist = delta.length()
        speed = float(getattr(unit, "speed", 120.0))
        step = speed * float(dt or 0)
        tag = label or "move"

        if step <= 0 and self._should_log_move(unit, f"{tag}_dt_zero"):
            _rts_log.warning(
                "move %s ZERO_DT worker@%s dt=%s speed=%s dist=%.1f goal=%s",
                tag,
                unit.rect.center,
                dt,
                speed,
                dist,
                (int(goal.x), int(goal.y)),
            )

        reach = max(_GATHER_REACH_RADIUS, step)
        if dist <= reach:
            if self._should_log_move(unit, f"{tag}_arrived", interval=1.0):
                _rts_log.debug(
                    "move %s ARRIVED worker@%s goal=%s dist=%.1f dt=%.4f",
                    tag,
                    unit.rect.center,
                    (int(goal.x), int(goal.y)),
                    dist,
                    float(dt or 0),
                )
            return True

        if dist > 0:
            move = delta.normalize() * min(step, dist)
            move_ix = int(move.x)
            move_iy = int(move.y)
            old = unit.rect.center
            if move_ix == 0 and move_iy == 0 and self._should_log_move(unit, f"{tag}_zero_int"):
                _rts_log.warning(
                    "move %s ZERO_INT worker@%s dt=%.4f step=%.3f dist=%.1f "
                    "move_raw=(%.3f,%.3f) goal=%s",
                    tag,
                    old,
                    float(dt or 0),
                    step,
                    dist,
                    move.x,
                    move.y,
                    (int(goal.x), int(goal.y)),
                )
            unit.rect.centerx += move_ix
            unit.rect.centery += move_iy
            hits = self._collision_hits(unit, obstacle_sprites)
            if hits:
                unit.rect.center = old
                if self._should_log_move(unit, f"{tag}_blocked"):
                    _rts_log.debug(
                        "move %s BLOCKED worker@%s dt=%.4f step=%.3f dist=%.1f "
                        "tried=(%d,%d) hits=%d [%s]",
                        tag,
                        old,
                        float(dt or 0),
                        step,
                        dist,
                        move_ix,
                        move_iy,
                        len(hits),
                        self._hit_summary(unit, hits),
                    )
            elif (unit.rect.center != old) and self._should_log_move(
                unit, f"{tag}_ok", interval=1.0
            ):
                _rts_log.debug(
                    "move %s OK worker@%s -> %s dt=%.4f step=%.3f dist=%.1f delta=(%d,%d)",
                    tag,
                    old,
                    unit.rect.center,
                    float(dt or 0),
                    step,
                    dist,
                    move_ix,
                    move_iy,
                )
        return False

    def find_dropoff(self, sprites, building_type):
        for sprite in sprites:
            if getattr(sprite, "kind", "") == "rts_building":
                if getattr(sprite, "dropoff_kind", "") == str(building_type):
                    return sprite
        return None
