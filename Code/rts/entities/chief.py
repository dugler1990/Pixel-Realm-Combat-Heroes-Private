import math
import random

import pygame

from ..assets import load_sprite, normalize_faction_id


class ChiefNPC(pygame.sprite.Sprite):
    """Roaming chief; opens population UI when selected on matching throne."""

    def __init__(self, pos, groups, config, registry=None):
        super().__init__(groups)
        self.kind = "chief"
        self.config = dict(config)
        self.chief_id = str(config.get("chief_id", id(self)))
        self.faction_id = normalize_faction_id(config.get("faction_id", ""))
        self.display_name = str(config.get("display_name", "Chief"))
        self.throne_id = str(config.get("throne_id", ""))
        self.roam_radius = int(config.get("roam_radius", 80))
        self.population_total = int(config.get("population_total", 10))
        self.population_workers = int(config.get("population_workers", 0))
        self.population_fighters = int(config.get("population_fighters", 0))
        self.sprite_key = str(config.get("sprite", "chief_eskimo"))
        self.spawn_center = pygame.math.Vector2(pos)
        self.worker_sprite_key = (
            "worker_jungle" if self.faction_id == "jungle_tribe" else "worker_eskimo"
        )

        self.image = load_sprite(self.sprite_key)
        self.rect = self.image.get_rect(center=pos)
        self.rts_selectable = True
        self.interacting = False
        self._wait_timer = 0.0
        self._target = None
        self.spawned_workers = []
        self.registry = registry

        self.rts_definition = {
            "id": self.chief_id,
            "display_name": self.display_name,
            "description": f"Chief of {self.faction_id}.",
            "actions": [],
        }
        if registry is not None:
            registry.register_chief(self)

    @property
    def population_idle(self):
        return max(
            0,
            self.population_total - self.population_workers - self.population_fighters,
        )

    def update(self, dt, obstacles=None):
        if self.interacting:
            return
        self._wait_timer -= float(dt or 0)
        if self._target is None or self._wait_timer <= 0:
            self._pick_roam_target()
            self._wait_timer = random.uniform(2.0, 4.0)
        if self._target is not None:
            self._move_toward(self._target, dt, obstacles)

    def _pick_roam_target(self):
        angle = random.uniform(0, 360)
        dist = random.uniform(0, self.roam_radius)
        rad = math.radians(angle)
        self._target = (
            int(self.spawn_center.x + math.cos(rad) * dist),
            int(self.spawn_center.y + math.sin(rad) * dist),
        )

    def _move_toward(self, target, dt, obstacles):
        pos = pygame.math.Vector2(self.rect.center)
        goal = pygame.math.Vector2(target)
        delta = goal - pos
        speed = 40.0
        step = speed * float(dt or 0)
        if delta.length() <= step:
            self.rect.center = (int(goal.x), int(goal.y))
            self._target = None
            return
        move = delta.normalize() * step
        self.rect.centerx += int(move.x)
        self.rect.centery += int(move.y)

    def add_worker_pop(self, worker_sprite):
        self.population_workers += 1
        self.spawned_workers.append(worker_sprite)

    def remove_idle_worker(self):
        for w in list(self.spawned_workers):
            if w.is_idle_for_despawn():
                self.spawned_workers.remove(w)
                self.population_workers = max(0, self.population_workers - 1)
                return w
        return None
