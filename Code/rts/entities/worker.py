from ..assets import load_sprite, normalize_faction_id
from ..build.states import BUILD_IDLE

import pygame

IDLE = "IDLE"
MOVING_TO_NODE = "MOVING_TO_NODE"
WAITING_AT_NODE = "WAITING_AT_NODE"
GATHERING = "GATHERING"
MOVING_TO_DROPOFF = "MOVING_TO_DROPOFF"
DELIVERING = "DELIVERING"
LOST = "LOST"


class RtsWorker(pygame.sprite.Sprite):
    def __init__(self, pos, groups, faction_id, sprite_key="worker_eskimo", chief=None):
        super().__init__(groups)
        self.kind = "rts_unit"
        self.faction_id = normalize_faction_id(faction_id)
        self.chief = chief
        self.gather_state = IDLE
        self.build_state = BUILD_IDLE
        self.speed = 120.0
        self.gather_lost = False
        self.build_lost = False
        self.assigned_node = None
        self.assigned_dropoff = None
        self.assigned_build_site = None
        self.assigned_building_id = ""
        self._build_timer = 0.0
        self._build_path = []
        self._build_path_index = 0
        self._build_world_adapter = None
        self._timer = 0.0
        self._registered = False
        self._delivery_category = ""
        self._delivery_amount = 0
        self.rts_selectable = True

        self.image = load_sprite(sprite_key)
        self.rect = self.image.get_rect(center=pos)
        self.rts_definition = {
            "id": "worker",
            "display_name": "Worker",
            "description": "Assign to gather resources.",
            "actions": [],
        }

    def is_idle_for_despawn(self):
        return (
            self.gather_state == IDLE
            and self.assigned_node is None
            and self.build_state == BUILD_IDLE
            and self.assigned_build_site is None
        )
