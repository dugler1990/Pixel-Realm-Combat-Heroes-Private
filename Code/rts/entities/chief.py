import pygame

from ..assets import load_sprite, normalize_faction_id
from ..combat_context import make_rts_combat_context
from ..tribe_monsters import monster_name_for_faction
from .tribe_member import RtsTribeMember


class RtsChiefEntity(RtsTribeMember):
    """Roaming chief; opens population UI when selected on matching throne."""

    def __init__(self, pos, groups, config, registry=None, obstacle_sprites=None, combat_context=None):
        config = dict(config or {})
        self.config = config
        self.chief_id = str(config.get("chief_id", id(self)))
        faction_id = normalize_faction_id(config.get("faction_id", ""))
        self.display_name = str(config.get("display_name", "Chief"))
        self.throne_id = str(config.get("throne_id", ""))
        self.roam_radius = int(config.get("roam_radius", 80))
        self.population_total = int(config.get("population_total", 10))
        self.population_workers = int(config.get("population_workers", 0))
        self.population_fighters = int(config.get("population_fighters", 0))
        sprite_key = str(config.get("sprite", "chief_eskimo"))
        self.worker_sprite_key = (
            "worker_jungle" if faction_id == "jungle_tribe" else "worker_eskimo"
        )
        if obstacle_sprites is None and groups:
            obstacle_sprites = groups[0]
        if combat_context is None:
            combat_context = make_rts_combat_context()

        super().__init__(
            pos,
            groups,
            faction_id,
            obstacle_sprites,
            combat_context,
            sprite_key=sprite_key,
            monster_name=monster_name_for_faction(faction_id, sprite_key),
            behavior="roam",
            center_pos=True,
            team_id="friendly",
            sprite_type="friendly",
        )
        self.kind = "chief"
        self.spawn_center = pygame.math.Vector2(pos)
        self.interacting = False
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


ChiefNPC = RtsChiefEntity
