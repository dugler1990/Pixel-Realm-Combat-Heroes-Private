from ..assets import load_sprite, normalize_faction_id
from ..categories import ALL_CATEGORIES

import pygame


class ResourceNode(pygame.sprite.Sprite):
    """Gather target configured entirely from Tiled properties."""

    def __init__(self, pos, groups, config, registry=None):
        super().__init__(groups)
        self.kind = "resource_node"
        self.config = dict(config)
        self.node_kind = str(config.get("node_kind", "node"))
        self.faction_id = normalize_faction_id(config.get("faction_id", ""))
        self.resource_category = str(config.get("resource_category", "food")).lower()
        self.yield_amount = int(config.get("yield_amount", 1))
        self.gather_duration = float(config.get("gather_duration", 5))
        self.max_workers = int(config.get("max_workers", 2))
        self.depletable = str(config.get("depletable", "false")).lower() in (
            "1",
            "true",
            "yes",
        )
        self.respawn_seconds = float(config.get("respawn_seconds", 0) or 0)
        self.dropoff_kind = str(config.get("dropoff_kind", ""))
        self.sprite_key = str(config.get("sprite", f"node_{self.node_kind}"))
        offset_y = int(config.get("gather_offset_y", 0))
        self.remaining_cycles = int(config.get("initial_cycles", 5)) if self.depletable else -1
        self._active_workers = 0
        self._waiting = []
        self.depleted = False
        self._respawn_timer = 0.0
        self.highlighted = False
        self.rts_selectable = True

        self.image = load_sprite(self.sprite_key)
        self.rect = self.image.get_rect(center=pos)
        self.gather_point = (self.rect.centerx, self.rect.centery + offset_y)
        self.display_name = self.node_kind.replace("_", " ").title()
        self.rts_definition = {
            "id": self.node_kind,
            "display_name": self.display_name,
            "description": f"{self.resource_category.upper()} source",
            "actions": [],
        }
        if registry is not None:
            registry.register_node(self)

    def is_active(self):
        return not self.depleted

    def has_free_slot(self):
        if not self.is_active():
            return False
        return self._active_workers < self.max_workers

    def register_worker(self):
        self._active_workers += 1

    def unregister_worker(self):
        self._active_workers = max(0, self._active_workers - 1)
        if self._waiting and self.has_free_slot():
            self._waiting.pop(0)

    def complete_gather_cycle(self):
        if not self.depletable or self.remaining_cycles < 0:
            return
        self.remaining_cycles -= 1
        if self.remaining_cycles <= 0:
            self.depleted = True
            self._respawn_timer = self.respawn_seconds

    def update(self, dt):
        if self.depleted and self.respawn_seconds > 0:
            self._respawn_timer -= float(dt or 0)
            if self._respawn_timer <= 0:
                self.depleted = False
                self.remaining_cycles = int(self.config.get("initial_cycles", 5))

    def source_row(self):
        return {
            "category": self.resource_category,
            "yieldAmount": self.yield_amount,
            "gatherDuration": self.gather_duration,
            "dropoffBuilding": self.dropoff_kind,
        }
