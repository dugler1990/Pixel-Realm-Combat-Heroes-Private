from ..build.states import BUILD_IDLE
from ..combat_context import make_rts_combat_context
from .gather_states import (
    DELIVERING,
    GATHERING,
    IDLE,
    LOST,
    MOVING_TO_DROPOFF,
    MOVING_TO_NODE,
    WAITING_AT_NODE,
)
from .worker_entity import RtsWorkerEntity


class RtsWorker(RtsWorkerEntity):
    """Backward-compatible alias used by gather/build tests."""

    def __init__(self, pos, groups, faction_id, sprite_key="worker_eskimo", chief=None):
        obstacle_sprites = groups[0] if groups else None
        super().__init__(
            pos,
            groups,
            faction_id,
            sprite_key=sprite_key,
            chief=chief,
            obstacle_sprites=obstacle_sprites,
            combat_context=make_rts_combat_context(),
        )

    def is_idle_for_despawn(self):
        return (
            self.gather_state == IDLE
            and self.assigned_node is None
            and self.build_state == BUILD_IDLE
            and self.assigned_build_site is None
        )
