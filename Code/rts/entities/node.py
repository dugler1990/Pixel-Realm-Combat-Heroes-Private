from ..assets import load_sprite, normalize_faction_id
from ..gather_slots import GatherSlotBook, build_gather_slot_positions
from ..visual_sequence import LayeredAmountVisual

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
        raw_layers = config.get("visual_layers") or config.get("visualLayers")
        self.max_ice = int(config.get("max_ice", config.get("maxIce", 0)) or 0)
        self._ice_visual = None
        if raw_layers or self.max_ice > 0:
            self.max_ice = self.max_ice or 100
            self._ice_visual = LayeredAmountVisual(
                raw_layers or [],
                max_ice=self.max_ice,
                fallback_size=self.image.get_size(),
            )
            self.depletable = True
            self.remaining_cycles = -1
        self.gather_point = (self.rect.centerx, self.rect.centery + offset_y)
        slot_count = max(1, self.max_workers)
        slot_positions = build_gather_slot_positions(
            self.gather_point,
            slot_count,
            cols=int(config.get("gather_slot_cols", 5) or 5),
            spacing=int(config.get("gather_slot_spacing", 22) or 22),
            front_offset_y=int(config.get("gather_slot_front_y", 18) or 18),
        )
        self._gather_slots = GatherSlotBook(slot_positions)
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
        if self._ice_visual is not None:
            return not self._ice_visual.is_depleted()
        return not self.depleted

    def has_free_slot(self):
        if not self.is_active():
            return False
        return self._gather_slots.has_free()

    def gather_goal_for(self, worker):
        goal = self._gather_slots.goal_for(worker)
        return goal if goal is not None else self.gather_point

    def register_worker(self, worker=None):
        if worker is not None:
            if self._gather_slots.claim(worker) is None:
                return False
        self._active_workers += 1
        return True

    def unregister_worker(self, worker=None):
        if worker is not None:
            self._gather_slots.release(worker)
        self._active_workers = max(0, self._active_workers - 1)
        if self._waiting and self.has_free_slot():
            self._waiting.pop(0)

    def complete_gather_cycle(self):
        if self._ice_visual is not None:
            return
        if not self.depletable or self.remaining_cycles < 0:
            return
        self.remaining_cycles -= 1
        if self.remaining_cycles <= 0:
            self.depleted = True
            self._respawn_timer = self.respawn_seconds

    def drain_ice(self, amount):
        if self._ice_visual is None:
            return False
        changed = self._ice_visual.drain(amount)
        self.refresh_visual()
        if self._ice_visual.is_depleted():
            self.depleted = True
            self._respawn_timer = self.respawn_seconds
        return changed

    def refresh_visual(self):
        if self._ice_visual is not None:
            self._ice_visual.apply_to_sprite(self)

    @property
    def ice_remaining(self):
        if self._ice_visual is None:
            return -1
        return self._ice_visual.ice_remaining

    def update(self, dt):
        if self._ice_visual is not None:
            self._ice_visual.update(float(dt or 0))
            self.refresh_visual()
        if self.depleted and self.respawn_seconds > 0:
            self._respawn_timer -= float(dt or 0)
            if self._respawn_timer <= 0:
                self.depleted = False
                if self._ice_visual is not None:
                    self._ice_visual.reset()
                    self.refresh_visual()
                else:
                    self.remaining_cycles = int(self.config.get("initial_cycles", 5))

    def source_row(self):
        return {
            "category": self.resource_category,
            "yieldAmount": self.yield_amount,
            "gatherDuration": self.gather_duration,
            "dropoffBuilding": self.dropoff_kind,
        }
