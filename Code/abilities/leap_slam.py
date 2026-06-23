"""Hold-to-charge leap slam with landing shockwave."""

from __future__ import annotations

import math

import pygame

from abilities.base import PlayerAbility
from abilities.dash import entity_speed
from abilities.protocol import PlayerAbilityContext
from hashRect import HashableRect
from Interaction import InteractionContext


class ChargedLeapSlamAbility(PlayerAbility):
    def __init__(self, ability_id: str, config: dict):
        self.ability_id = ability_id
        self.config = dict(config)

    def is_active(self, entity) -> bool:
        return (
            getattr(entity, "_charge_runtime", None) is not None
            or getattr(entity, "_leap_runtime", None) is not None
        )

    def suppresses_input(self, entity) -> bool:
        return self.is_active(entity)

    def suppresses_locomotion(self, entity) -> bool:
        return getattr(entity, "_leap_runtime", None) is not None or getattr(entity, "_dash_runtime", None) is not None

    def charge_ratio(self, entity) -> float:
        runtime = getattr(entity, "_charge_runtime", None)
        if runtime is None:
            return 0.0
        return self._raw_charge_ratio(runtime)

    def _raw_charge_ratio(self, runtime) -> float:
        elapsed = pygame.time.get_ticks() - runtime["start_time"]
        max_hold = int(self.config.get("max_hold_ms", 1200))
        if max_hold <= 0:
            return 1.0
        return min(1.0, elapsed / max_hold)

    def _leap_distance(self, direction: str, charge_ratio: float) -> float:
        horizontal = float(self.config.get("max_horizontal_range", 180))
        vertical = float(self.config.get("max_vertical_range", horizontal))
        span = vertical if direction in ("up", "down") else horizontal
        return span * charge_ratio

    def _leap_delta(self, direction: str, distance: float) -> tuple[int, int]:
        if direction == "left":
            return (-int(distance), 0)
        if direction == "up":
            return (0, -int(distance))
        if direction == "down":
            return (0, int(distance))
        return (int(distance), 0)

    def _air_duration_ms(self, charge_ratio: float) -> int:
        fallback = int(self.config.get("air_duration_ms", 400))
        min_ms = int(self.config.get("air_duration_min_ms", fallback // 2))
        max_ms = int(self.config.get("air_duration_max_ms", fallback))
        if max_ms < min_ms:
            max_ms = min_ms
        ratio = max(0.0, min(1.0, float(charge_ratio)))
        return int(min_ms + (max_ms - min_ms) * ratio)

    def _travel_progress(self, t: float) -> float:
        power = float(self.config.get("travel_ease_power", 2.0))
        power = max(0.1, power)
        return 1.0 - (1.0 - t) ** power

    def _arc_offset(self, t: float, arc_height: float) -> float:
        rise = float(self.config.get("arc_rise_ratio", 0.35))
        hang = float(self.config.get("arc_hang_ratio", 0.12))
        rise = max(0.05, min(0.8, rise))
        hang = max(0.0, min(0.5, hang))
        fall_start = min(0.95, rise + hang)

        if t <= rise:
            u = t / rise
            peak = 1.0 - (1.0 - u) ** 2
        elif t <= fall_start:
            peak = 1.0
        else:
            span = max(0.05, 1.0 - fall_start)
            u = (t - fall_start) / span
            peak = max(0.0, 1.0 - u ** 2)
        return arc_height * peak

    def _airborne_base_position(self, runtime, t: float) -> tuple[int, int]:
        t = max(0.0, min(1.0, t))
        direction = runtime.get("direction", "right")
        travel_t = self._travel_progress(t)
        lerped_x = runtime["start_x"] + (runtime["end_x"] - runtime["start_x"]) * travel_t
        lerped_y = runtime["start_y"] + (runtime["end_y"] - runtime["start_y"]) * travel_t
        arc_height = float(runtime.get("arc_height", self._arc_height_for_ratio(runtime.get("charge_ratio", 1.0))))
        arc = self._arc_offset(t, arc_height)

        if direction in ("left", "right"):
            return int(lerped_x), int(runtime["start_y"] - arc)
        if direction == "up":
            return int(lerped_x), int(lerped_y - arc)
        return int(lerped_x), int(lerped_y)

    def _accumulate_air_control(self, entity, runtime, dt) -> None:
        max_steer = float(runtime.get("max_air_steer", 0))
        if max_steer <= 0:
            return
        dx = float(getattr(entity.direction, "x", 0))
        dy = float(getattr(entity.direction, "y", 0))
        if dx == 0 and dy == 0:
            return
        length = math.hypot(dx, dy)
        dx /= length
        dy /= length
        frame_scale = float(dt) * 60.0 if dt else 1.0
        step = float(self.config.get("air_control_speed", 2.5)) * frame_scale
        steer_x = float(runtime.get("air_steer_x", 0.0)) + dx * step
        steer_y = float(runtime.get("air_steer_y", 0.0)) + dy * step
        mag = math.hypot(steer_x, steer_y)
        if mag > max_steer:
            scale = max_steer / mag
            steer_x *= scale
            steer_y *= scale
        runtime["air_steer_x"] = steer_x
        runtime["air_steer_y"] = steer_y

    def _sync_airborne_position(self, entity, runtime, t: float, dt) -> None:
        base_x, base_y = self._airborne_base_position(runtime, t)
        self._accumulate_air_control(entity, runtime, dt)
        entity.hitbox.x = int(base_x + float(runtime.get("air_steer_x", 0.0)))
        entity.hitbox.y = int(base_y + float(runtime.get("air_steer_y", 0.0)))
        entity.rect.center = entity.hitbox.center

    def _apply_launch_snap(self, entity, runtime) -> None:
        snap = int(self.config.get("launch_snap_px", 0))
        if snap <= 0:
            return
        dx = runtime["end_x"] - runtime["start_x"]
        dy = runtime["end_y"] - runtime["start_y"]
        dist = math.hypot(dx, dy)
        if dist <= 0:
            return
        entity.hitbox.x += int(snap * dx / dist)
        entity.hitbox.y += int(snap * dy / dist)
        entity.rect.center = entity.hitbox.center

    def _arc_height_for_ratio(self, charge_ratio: float) -> float:
        min_h = float(self.config.get("min_arc_height", self.config.get("arc_height", 64)))
        max_h = float(self.config.get("max_arc_height", min_h * 5))
        ratio = max(0.0, min(1.0, float(charge_ratio)))
        return min_h + (max_h - min_h) * ratio

    def on_press(self, entity, context, direction="right", **kwargs) -> bool:
        if self.is_active(entity):
            return False
        if getattr(entity, "_dash_runtime", None) is not None:
            return False
        cost = int(self.config.get("cost", 0))
        if getattr(entity, "energy", 0) < cost:
            return False
        entity._charge_runtime = {
            "start_time": pygame.time.get_ticks(),
            "direction": direction,
            "charge_ratio": 0.0,
            "_ability": self,
        }
        presentation = self.config.get("presentation") or {}
        status_template = presentation.get("charge_status")
        if status_template and hasattr(entity, "status"):
            entity.status = status_template.format(dir=direction)
        if hasattr(entity, "attacking"):
            entity.attacking = False
        return True

    def on_release(self, entity, context, direction=None, **kwargs) -> bool:
        runtime = getattr(entity, "_charge_runtime", None)
        if runtime is None:
            return False
        direction = runtime.get("direction") or direction or "right"
        charge_ratio = self._compute_charge_ratio(runtime)
        entity._charge_runtime = None
        return self._launch(entity, context, direction, charge_ratio)

    def tick(self, entity, context, dt, QuadTree, entity_quad_tree) -> None:
        charge_runtime = getattr(entity, "_charge_runtime", None)
        if charge_runtime is not None:
            self._tick_charge(entity, charge_runtime, context, direction=charge_runtime.get("direction", "right"))
            return

        leap_runtime = getattr(entity, "_leap_runtime", None)
        if leap_runtime is None:
            return

        phase = leap_runtime.get("phase", "airborne")
        if phase == "airborne":
            self._tick_airborne(entity, leap_runtime, dt)
            return
        if phase == "impact":
            self._resolve_landing_aoe(entity, context, entity_quad_tree, leap_runtime)
            self._end(entity, leap_runtime)

    def _tick_charge(self, entity, runtime, context, direction="right") -> None:
        now = pygame.time.get_ticks()
        elapsed = now - runtime["start_time"]
        max_hold = int(self.config.get("max_hold_ms", 1200))
        if hasattr(entity, "get_direction_as_string"):
            direction = entity.get_direction_as_string()
            runtime["direction"] = direction
            presentation = self.config.get("presentation") or {}
            status_template = presentation.get("charge_status")
            if status_template and hasattr(entity, "status"):
                entity.status = status_template.format(dir=direction)
        if elapsed >= max_hold:
            entity._charge_runtime = None
            self._launch(entity, context, direction, 1.0)
            return
        runtime["charge_ratio"] = self._raw_charge_ratio(runtime)

    def _compute_charge_ratio(self, runtime) -> float:
        elapsed = pygame.time.get_ticks() - runtime["start_time"]
        max_hold = int(self.config.get("max_hold_ms", 1200))
        min_hold = int(self.config.get("min_hold_ms", 0))
        min_ratio = float(self.config.get("min_charge_ratio", 0.25))
        if max_hold <= 0:
            return 1.0
        raw = min(1.0, elapsed / max_hold)
        if elapsed < min_hold:
            return min_ratio
        return max(min_ratio, raw)

    def _launch(self, entity, context, direction, charge_ratio) -> bool:
        cost = int(self.config.get("cost", 0))
        energy = getattr(entity, "energy", 0)
        if energy < cost:
            return False
        entity.energy = energy - cost

        distance = self._leap_distance(direction, charge_ratio)
        dx, dy = self._leap_delta(direction, distance)
        start_x = entity.hitbox.x
        start_y = entity.hitbox.y
        end_x = start_x + dx
        end_y = start_y + dy
        now = pygame.time.get_ticks()
        air_duration = self._air_duration_ms(charge_ratio)

        presentation = self.config.get("presentation") or {}
        max_steer = distance * float(self.config.get("air_control_max_ratio", 0.12))
        entity._leap_runtime = {
            "phase": "airborne",
            "direction": direction,
            "charge_ratio": charge_ratio,
            "arc_height": self._arc_height_for_ratio(charge_ratio),
            "start_x": start_x,
            "start_y": start_y,
            "end_x": end_x,
            "end_y": end_y,
            "start_time": now,
            "end_time": now + air_duration,
            "impact_center": (end_x, end_y),
            "air_steer_x": 0.0,
            "air_steer_y": 0.0,
            "max_air_steer": max_steer,
            "_ability": self,
            "end_status_template": presentation.get("end_status", "{dir}_idle"),
        }

        air_status = presentation.get("air_status")
        if air_status and hasattr(entity, "status"):
            entity.status = air_status.format(dir=direction)
        if hasattr(entity, "frame_index"):
            entity.frame_index = 0
        self._apply_launch_snap(entity, entity._leap_runtime)
        return True

    def _tick_airborne(self, entity, runtime, dt=None) -> None:
        now = pygame.time.get_ticks()
        if now >= runtime["end_time"]:
            base_x, base_y = self._airborne_base_position(runtime, 1.0)
            entity.hitbox.x = int(base_x + float(runtime.get("air_steer_x", 0.0)))
            entity.hitbox.y = int(base_y + float(runtime.get("air_steer_y", 0.0)))
            entity.rect.center = entity.hitbox.center
            runtime["impact_center"] = entity.hitbox.center
            runtime["phase"] = "impact"
            presentation = self.config.get("presentation") or {}
            land_status = presentation.get("land_status")
            if land_status and hasattr(entity, "status"):
                entity.status = land_status.format(dir=runtime.get("direction", "right"))
            return

        duration = max(1, runtime["end_time"] - runtime["start_time"])
        t = (now - runtime["start_time"]) / duration
        self._sync_airborne_position(entity, runtime, t, dt)

    def _resolve_landing_aoe(self, entity, context, entity_quad_tree, runtime) -> None:
        if entity_quad_tree is None:
            return

        charge_ratio = float(runtime.get("charge_ratio", 1.0))
        min_radius = float(self.config.get("min_impact_radius", 40))
        max_radius = float(self.config.get("max_impact_radius", 120))
        radius = min_radius + (max_radius - min_radius) * charge_ratio
        base_damage = float(self.config.get("base_damage", 0))
        base_knockback = float(self.config.get("base_knockback", 0))
        attack_type = self.config.get("damage_attack_type", "weapon")
        follow_through = float(self.config.get("velocity_follow_through", 0.5))
        entity.impulse_follow_through = follow_through

        center_x, center_y = runtime.get("impact_center", entity.hitbox.center)
        query_rect = pygame.Rect(0, 0, int(radius * 2), int(radius * 2))
        query_rect.center = (center_x, center_y)
        entity_id = getattr(entity, "id", None)
        nearby = entity_quad_tree.hit(HashableRect(query_rect, entity_id))

        resolver = None
        level = getattr(entity, "level", None)
        if level is not None:
            resolver = getattr(level, "interaction_resolver", None)

        presentation = self.config.get("presentation") or {}
        particle_template = presentation.get("particle_template")
        if particle_template and isinstance(context, PlayerAbilityContext):
            animation_player = context.animation_player
            if animation_player is not None:
                direction = runtime.get("direction", "right")
                particle_key = particle_template
                if not animation_player.frames.get(particle_key):
                    particle_key = f"slide_{direction}" if direction in ("left", "right") else particle_template
                if animation_player.frames.get(particle_key):
                    animation_player.create_particles(
                        particle_key,
                        (center_x, center_y),
                        entity.groups(),
                    )

        for target in nearby:
            if target is entity:
                continue
            tx, ty = target.hitbox.center
            dist = math.hypot(tx - center_x, ty - center_y)
            if dist > radius:
                continue
            falloff = max(0.0, 1.0 - dist / radius) if radius > 0 else 0.0
            damage_amount = base_damage * charge_ratio * falloff
            knockback_mag = base_knockback * charge_ratio * falloff
            if dist == 0:
                nx, ny = 1.0, 0.0
            else:
                nx = (tx - center_x) / dist
                ny = (ty - center_y) / dist

            if damage_amount > 0:
                dmg_ctx = InteractionContext(
                    kind="damage",
                    source_kind="leap_slam",
                    source=entity,
                    owner=entity,
                    source_team=getattr(entity, "team_id", None),
                    target=target,
                    amount=damage_amount,
                    attack_type=attack_type,
                )
                if resolver is not None:
                    if resolver.can_potentially_affect(
                        getattr(entity, "team_id", None),
                        getattr(target, "team_id", None),
                        "damage",
                    ):
                        resolver.apply(dmg_ctx)
                elif hasattr(target, "can_receive_interaction") and target.can_receive_interaction(dmg_ctx):
                    target.receive_interaction(dmg_ctx)

            if knockback_mag > 0:
                imp_ctx = InteractionContext(
                    kind="impulse",
                    source_kind="leap_slam",
                    source=entity,
                    owner=entity,
                    source_team=getattr(entity, "team_id", None),
                    target=target,
                    impulse_x=nx * knockback_mag,
                    impulse_y=ny * knockback_mag,
                )
                if resolver is not None:
                    resolver.apply(imp_ctx)
                elif hasattr(target, "can_receive_interaction") and target.can_receive_interaction(imp_ctx):
                    target.receive_interaction(imp_ctx)

    def _end(self, entity, runtime) -> None:
        entity._leap_runtime = None
        entity._charge_runtime = None
        direction = runtime.get("direction", "right")
        if hasattr(entity, "status"):
            template = runtime.get("end_status_template", "{dir}_idle")
            entity.status = template.format(dir=direction)

    def try_start(self, entity, context, **kwargs) -> bool:
        return False
