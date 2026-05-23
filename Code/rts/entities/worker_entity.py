import pygame

from Entity import Entity
from Interaction import InteractionContext
from hashRect import HashableRect

from ..assets import load_sprite, normalize_faction_id
from ..build.states import BUILD_IDLE
from .worker import (
    DELIVERING,
    GATHERING,
    IDLE,
    LOST,
    MOVING_TO_DROPOFF,
    MOVING_TO_NODE,
    WAITING_AT_NODE,
)


class RtsWorkerEntity(Entity):
    """RTS worker present in the adventure world; gather AI moves rect directly."""

    def __init__(
        self,
        pos,
        groups,
        faction_id,
        sprite_key="worker_eskimo",
        chief=None,
        layout_callback_update_quad_tree=None,
        world_sim=None,
        health=50,
    ):
        self._quad_tree_callback_provided = layout_callback_update_quad_tree is not None
        super().__init__(
            groups,
            layout_callback_update_quad_tree=layout_callback_update_quad_tree,
        )
        self.kind = "rts_unit"
        self.faction_id = normalize_faction_id(faction_id)
        self.chief = chief
        self.world_sim = world_sim
        self.gather_state = IDLE
        self.build_state = BUILD_IDLE
        self.speed = 120.0
        self.gather_lost = False
        self.build_lost = False
        self.assigned_node = None
        self.assigned_dropoff = None
        self.assigned_build_site = None
        self.assigned_building_id = ""
        self._build_path = []
        self._build_path_index = 0
        self._build_path_planned = False
        self._build_timer = 0.0
        self._build_world_adapter = None
        self._timer = 0.0
        self._registered = False
        self._delivery_category = ""
        self._delivery_amount = 0
        self.rts_selectable = True
        self.team_id = "neutral_passive"
        self.vulnerable = True
        self.health = int(health)
        self.sprite_type = "rts_worker"

        self.image = load_sprite(sprite_key)
        self.rect = self.image.get_rect(center=pos)
        self.hitbox = self.rect.inflate(0, -6)
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

    def can_receive_interaction(self, ctx: InteractionContext):
        if ctx.kind == "effect_state":
            return True
        if ctx.kind != "damage":
            return False
        if ctx.source_team == self.team_id:
            return False
        return self.health > 0

    def receive_interaction(self, ctx: InteractionContext):
        if ctx.kind == "effect_state":
            super().receive_interaction(ctx)
            return
        if ctx.kind != "damage":
            return
        amount = ctx.amount
        if amount is None:
            source = ctx.source
            if source is not None and hasattr(source, "get_full_weapon_damage"):
                if ctx.attack_type == "weapon":
                    amount = source.get_full_weapon_damage()
                elif hasattr(source, "get_full_magic_damage"):
                    amount = source.get_full_magic_damage()
        if amount is None:
            return
        if self.vulnerable:
            self.health -= int(amount)
            self.check_death()

    def check_death(self):
        if self.health > 0:
            return
        if self._quad_tree_callback_provided:
            self.layout_callback_update_quad_tree(
                obstacle_sprite=HashableRect(self.rect, self.id),
                remove_existing=True,
                alive=False,
            )
        sim = getattr(self, "world_sim", None)
        if sim is not None:
            sim.on_worker_death(self)
        self.kill()


# Re-export gather state constants for tests and gather controller
__all__ = [
    "RtsWorkerEntity",
    "IDLE",
    "MOVING_TO_NODE",
    "WAITING_AT_NODE",
    "GATHERING",
    "MOVING_TO_DROPOFF",
    "DELIVERING",
    "LOST",
]
