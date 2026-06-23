"""One-shot evasion abilities (ice clone)."""

from __future__ import annotations

from abilities.base import PlayerAbility
from abilities.protocol import PlayerAbilityContext
from IceClone import IceClone


class InstantEvasionAbility(PlayerAbility):
    def __init__(self, ability_id: str, config: dict):
        self.ability_id = ability_id
        self.config = dict(config)

    def try_start(self, entity, context, **kwargs) -> bool:
        cost = int(self.config.get("cost", 0))
        if getattr(entity, "energy", 0) < cost:
            return False

        entity.energy -= cost
        create_trap = None
        if isinstance(context, PlayerAbilityContext):
            create_trap = context.create_trap
        if create_trap is None:
            create_trap = getattr(entity, "create_trap", None)
        if create_trap is None:
            return False

        trap_config = {
            "class": IceClone,
            "pos": entity.rect.center,
            "groups": entity.groups(),
            "image_path": "../Graphics/Traps/Ice/ice_clone.png",
            "effect_type": self.config.get("effect_type", "freeze"),
            "trigger": "proximity",
            "death_animation": "ice_clone_death_1",
            "lifespan": self.config.get("lifespan", 3000),
            "radius": self.config.get("radius", 5),
            "health": 100,
            "exp_value": 50,
            "owner": entity,
            "source_team": getattr(entity, "team_id", "player"),
            "source_kind": "special",
            "attack_type": self.config.get("effect_type", "freeze"),
            "amount": None,
            "tags": {"summon", "special"},
        }
        create_trap(trap_config)
        return True
