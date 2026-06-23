"""Base class for player abilities."""

from __future__ import annotations

from abc import ABC, abstractmethod


class PlayerAbility(ABC):
    ability_id: str

    @abstractmethod
    def try_start(self, entity, context, **kwargs) -> bool:
        raise NotImplementedError

    def tick(self, entity, context, dt, QuadTree, entity_quad_tree) -> None:
        return None

    def is_active(self, entity) -> bool:
        return False

    def suppresses_input(self, entity) -> bool:
        return False

    def suppresses_locomotion(self, entity) -> bool:
        return False
