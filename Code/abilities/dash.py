"""Timer-based dash / slide ability."""

from __future__ import annotations

import pygame

from abilities.base import PlayerAbility
from abilities.protocol import CombatAbilityContext, PlayerAbilityContext
from hashRect import HashableRect
from Interaction import InteractionContext

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
            "hit_targets": set(),
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

        pre_x = entity.hitbox.x
        entity.hitbox.x += int(delta)
        entity.rect.center = entity.hitbox.center

        collision_mode = runtime["collision_mode"]
        if collision_mode == "resolve":
            entity.collision(QuadTree, entity_quad_tree, speed=abs(delta))
            if runtime["stop_on_wall"] and int(delta) != 0 and entity.hitbox.x == pre_x:
                self._end(entity, runtime)
                return
        elif collision_mode == "damage_on_hit":
            self._apply_damage_on_hit(entity, context, entity_quad_tree, runtime)

    def _apply_damage_on_hit(self, entity, context, entity_quad_tree, runtime) -> None:
        if entity_quad_tree is None or runtime.get("damage") is None:
            return

        entity_id = getattr(entity, "id", None)
        query = HashableRect(entity.rect, entity_id)
        nearby = entity_quad_tree.hit(query)
        resolver = None
        if isinstance(context, CombatAbilityContext):
            resolver = context.interaction_resolver()

        for target in nearby:
            if target is entity:
                continue
            target_id = getattr(target, "id", id(target))
            if runtime["hit_once_per_target"] and target_id in runtime["hit_targets"]:
                continue

            ctx = InteractionContext(
                kind="damage",
                source_kind="dash",
                source=entity,
                owner=entity,
                source_team=getattr(entity, "team_id", None),
                target=target,
                amount=runtime["damage"],
                attack_type=runtime["attack_type"],
            )
            if resolver is not None:
                if not resolver.can_potentially_affect(
                    getattr(entity, "team_id", None),
                    getattr(target, "team_id", None),
                    ctx,
                ):
                    continue
                resolver.apply(ctx)
            elif hasattr(target, "can_receive_interaction") and target.can_receive_interaction(ctx):
                target.receive_interaction(ctx)
            else:
                continue

            if runtime["hit_once_per_target"]:
                runtime["hit_targets"].add(target_id)

    def _end(self, entity, runtime) -> None:
        entity._dash_runtime = None
        direction = runtime.get("direction", "right")
        if hasattr(entity, "status"):
            template = runtime.get("end_status_template", "{dir}_idle")
            entity.status = template.format(dir=direction)
