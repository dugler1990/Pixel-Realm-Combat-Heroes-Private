from ..build.states import BUILD_IDLE
from ..combat_context import make_rts_combat_context
from ..tribe_monsters import monster_name_for_faction
from .gather_states import (
    DELIVERING,
    GATHERING,
    IDLE,
    LOST,
    MOVING_TO_DROPOFF,
    MOVING_TO_NODE,
    WAITING_AT_NODE,
)
from .tribe_member import RtsTribeMember


class RtsWorkerEntity(RtsTribeMember):
    """RTS worker in the adventure world; locomotion via Entity.move + JobDriver."""

    def __init__(
        self,
        pos,
        groups,
        faction_id,
        sprite_key="worker_eskimo",
        chief=None,
        obstacle_sprites=None,
        combat_context=None,
        layout_callback_update_quad_tree=None,
        world_sim=None,
        health=50,
    ):
        if obstacle_sprites is None and groups:
            obstacle_sprites = groups[0]
        if combat_context is None:
            combat_context = make_rts_combat_context()
        self._quad_tree_callback_provided = layout_callback_update_quad_tree is not None
        super().__init__(
            pos,
            groups,
            faction_id,
            obstacle_sprites,
            combat_context,
            sprite_key=sprite_key,
            monster_name=monster_name_for_faction(faction_id, sprite_key),
            behavior="job",
            layout_callback_update_quad_tree=layout_callback_update_quad_tree,
            center_pos=True,
            health=health,
            team_id="neutral_passive",
            sprite_type="rts_worker",
        )
        self.kind = "rts_unit"
        self.chief = chief
        self.world_sim = world_sim
        self.gather_state = IDLE
        self.build_state = BUILD_IDLE
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
