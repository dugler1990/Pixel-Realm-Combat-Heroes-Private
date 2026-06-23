"""Entity contracts for ability simulation and presentation contexts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class DashEntity(Protocol):
    """Minimal simulation contract for DashAbility."""

    hitbox: Any
    rect: Any
    stats: dict
    _dash_runtime: Optional[dict]

    def collision(self, QuadTree, entity_quad_tree, speed=0): ...


@dataclass
class PlayerAbilityContext:
    """Presentation and level hooks for player-initiated abilities."""

    animation_player: Any = None
    create_trap: Any = None

    @classmethod
    def from_player(cls, player) -> "PlayerAbilityContext":
        level = getattr(player, "level", None)
        animation_player = getattr(level, "animation_player", None) if level else None
        create_trap = getattr(player, "create_trap", None)
        return cls(animation_player=animation_player, create_trap=create_trap)


@dataclass
class CombatAbilityContext:
    """Hooks for AI-driven abilities."""

    combat_context: dict | None = None

    @classmethod
    def from_enemy(cls, enemy) -> "CombatAbilityContext":
        return cls(combat_context=getattr(enemy, "combat_context", None))

    def interaction_resolver(self):
        ctx = self.combat_context or {}
        level = ctx.get("level")
        return getattr(level, "interaction_resolver", None) if level else None
