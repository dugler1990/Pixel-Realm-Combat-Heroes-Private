"""Timer-based dash / slide ability."""

from __future__ import annotations

import pygame

from abilities.base import PlayerAbility
from abilities.protocol import CombatAbilityContext, PlayerAbilityContext
import hit_core

STUB_COLLISION_MODES = frozenset()
IMPLEMENTED_COLLISION_MODES = frozenset({"pass_through", "resolve", "damage_on_hit"})


def entity_speed(entity) -> float:
    """Player uses stats['speed']; CombatUnit uses entity.speed."""
    stats = getattr(entity, "stats", None)
    if isinstance(stats, dict) and "speed" in stats:
        return float(stats["speed"])
    return float(getattr(entity, "speed", 0))


def validate_collision_mode(mode: str) -> None:
    if mode in IMPLEMENTED_COLLISION_MODES:
        return
    if mode in STUB_COLLISION_MODES:
        raise NotImplementedError(f"collision_mode {mode!r} is phase 2")
    raise ValueError(f"unknown collision_mode {mode!r}")


class DashAbility(PlayerAbility):
    def __init__(self, ability_id: str, config: dict):
        self.ability_id = ability_id
        self.config = dict(config)
        self.collision_mode = self.config.get("collision_mode", "pass_through")
        validate_collision_mode(self.collision_mode)

    def is_active(self, entity) -> bool:
        return getattr(entity, "_dash_runtime", None) is not None

    def suppresses_input(self, entity) -> bool:
        return self.is_active(entity)

    def suppresses_locomotion(self, entity) -> bool:
        return self.is_active(entity)

    def try_start(self, entity, context, direction="right", **kwargs) -> bool:
        if self.is_active(entity):
            return False
        cost = int(self.config.get("cost", 0))
        energy = getattr(entity, "energy", 0)
        if energy < cost:
            return False

        if cost:
            entity.energy = energy - cost

        presentation = self.config.get("presentation") or {}
        end_status_template = presentation.get("end_status", "{dir}_idle")

        entity._dash_runtime = {
            "direction": direction,
            "end_time": pygame.time.get_ticks() + int(self.config.get("duration_ms", 300)),
            "speed_mult": float(self.config.get("speed_mult", 3)),
            "collision_mode": self.collision_mode,
            "stop_on_wall": bool(self.config.get("stop_on_wall", False)),
            "damage": self.config.get("damage"),
            "attack_type": self.config.get("attack_type", "melee"),
            "hit_once_per_target": bool(self.config.get("hit_once_per_target", True)),
            "hits": {},
            "rehit_ms": self.config.get("rehit_ms"),
            "end_status_template": end_status_template,
            "_ability": self,
        }

        status_template = presentation.get("status_template")
        if status_template and hasattr(entity, "status"):
            entity.status = status_template.format(dir=direction)
        if hasattr(entity, "frame_index"):
            entity.frame_index = 0

        particle_template = presentation.get("particle_template")
        if particle_template and isinstance(context, PlayerAbilityContext):
            animation_player = context.animation_player
            if animation_player is not None:
                particle_effect = particle_template.format(dir=direction)
                animation_player.create_particles(
                    particle_effect,
                    entity.rect.center,
                    entity.groups(),
                )

        if hasattr(entity, "attacking"):
            entity.attacking = False
        if hasattr(entity, "direction"):
            entity.direction.x = 0
            entity.direction.y = 0

        return True

    def tick(self, entity, context, dt, QuadTree, entity_quad_tree) -> None:
        runtime = getattr(entity, "_dash_runtime", None)
        if runtime is None:
            return

        if pygame.time.get_ticks() >= runtime["end_time"]:
            self._end(entity, runtime)
            return

        direction = runtime["direction"]
        speed = entity_speed(entity)
        delta = speed * runtime["speed_mult"]
        if direction == "left":
            delta = -delta
        elif direction != "right":
            delta = 0

        collision_mode = runtime["collision_mode"]
        if collision_mode == "resolve":
            # As far as the walls let the feet go; stop_on_wall ends the dash on no x progress.
            moved_x, _ = entity.step_against_walls(int(delta), 0, QuadTree)
            entity.plant_sprite_on_hitbox()
            if runtime["stop_on_wall"] and int(delta) != 0 and moved_x == 0:
                self._end(entity, runtime)
            return

        entity.hitbox.x += int(delta)
        if collision_mode == "damage_on_hit":
            entity.plant_sprite_on_hitbox()
            self._apply_damage_on_hit(entity, context, entity_quad_tree, runtime)
        else:
            entity.plant_sprite_on_hitbox()

    def _apply_damage_on_hit(self, entity, context, entity_quad_tree, runtime) -> None:
        """Damage every body the dasher's pixels touch, by the dash's repeat rule.

        Bodies come from the entity tree around the dasher (hit_core.bodies_near).
        hit_once_per_target False keeps no record, so it hits every frame.
        """
        if runtime.get("damage") is None:
            return
        level = getattr(entity, "level", None)
        if level is None and isinstance(context, CombatAbilityContext):
            level = (context.combat_context or {}).get("level")
        resolver = getattr(level, "interaction_resolver", None)
        shape = hit_core.shape_of(entity)
        if resolver is None or shape is None:
            return
        nearby = hit_core.bodies_near(entity_quad_tree, shape.rect, getattr(entity, "id", -1))
        targets = hit_core.find_hits(shape, nearby, exclude=(entity,))
        resolver.strike(
            targets,
            hits=runtime["hits"] if runtime["hit_once_per_target"] else None,
            rehit_ms=runtime["rehit_ms"],
            kind="damage",
            source_kind="dash",
            source=entity,
            owner=entity,
            source_team=getattr(entity, "team_id", None),
            amount=runtime["damage"],
            attack_type=runtime["attack_type"],
        )

    def _end(self, entity, runtime) -> None:
        entity._dash_runtime = None
        direction = runtime.get("direction", "right")
        if hasattr(entity, "status"):
            template = runtime.get("end_status_template", "{dir}_idle")
            entity.status = template.format(dir=direction)
