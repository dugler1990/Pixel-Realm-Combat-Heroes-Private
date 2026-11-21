"""Escape path / pad sequencers for fog ordeals."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


Direction = str  # "N" | "E" | "S" | "W"


@dataclass
class EscapeRoute:
    name: str
    sequence: Sequence[Direction]
    # Optional destination metadata for later Level4 wiring; unused in suite v0.
    layout: str = ""
    tile: Tuple[int, int] = (0, 0)


@dataclass
class PathStateMachine:
    """Lost-Woods exit sequencer. Wrong step resets; matching a full route wins."""

    routes: List[EscapeRoute]
    steps: List[Direction] = field(default_factory=list)

    def push(self, direction: Direction) -> Optional[EscapeRoute]:
        self.steps.append(direction)
        alive = [r for r in self.routes if self._is_prefix(self.steps, r.sequence)]
        if not alive:
            self.steps.clear()
            return None
        for route in alive:
            if list(route.sequence) == self.steps:
                self.steps.clear()
                return route
        return None

    def reset(self) -> None:
        self.steps.clear()

    @staticmethod
    def _is_prefix(steps: Sequence[Direction], sequence: Sequence[Direction]) -> bool:
        if len(steps) > len(sequence):
            return False
        return list(sequence[: len(steps)]) == list(steps)


@dataclass
class PadSpec:
    pad_id: str
    angle_deg: float
    half_width_deg: float = 25.0


@dataclass
class PadSequence:
    """Ordered rim pads; wrong pad resets progress."""

    pads: List[PadSpec]
    order: List[str]
    progress: int = 0
    _last_pad: Optional[str] = None

    def hit(self, pad_id: str) -> bool:
        """Register a pad hit. Returns True if the full order is complete."""
        if pad_id == self._last_pad:
            return False
        self._last_pad = pad_id
        expected = self.order[self.progress] if self.progress < len(self.order) else None
        if pad_id != expected:
            self.progress = 0
            if self.order and pad_id == self.order[0]:
                self.progress = 1
            return False
        self.progress += 1
        if self.progress >= len(self.order):
            self.progress = 0
            self._last_pad = None
            return True
        return False

    def reset(self) -> None:
        self.progress = 0
        self._last_pad = None
