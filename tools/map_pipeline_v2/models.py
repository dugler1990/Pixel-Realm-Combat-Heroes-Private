"""Domain model: pure data + the level state machine. No I/O, no API keys.

Everything here is intended to be trivially unit-testable and importable without
side effects. Geometry helpers (coordinate transforms, overlap computation) will
be ported into a `world/` sub-package in Phase 1; for now the model carries the
shapes those functions produce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Size:
    width: int
    height: int

    def as_tuple(self) -> tuple[int, int]:
        return (self.width, self.height)


@dataclass(frozen=True)
class ImageRef:
    """A handle to an image on disk. Kept as a path in Phase 0."""

    path: Path

    def exists(self) -> bool:
        return Path(self.path).is_file()


@dataclass(frozen=True)
class MaskRef:
    """A handle to a single-channel (L) mask on disk. Non-zero = active."""

    path: Path

    def exists(self) -> bool:
        return Path(self.path).is_file()


# --------------------------------------------------------------------------- #
# World / levels
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Connection:
    """A neighbor relationship. `kind == "boat"` means no shared land pad."""

    neighbor_id: str
    kind: str = "land"


@dataclass(frozen=True)
class Level:
    level_id: str
    name: str
    region: str
    # Silhouette polygon in canvas pixel coordinates (x, y).
    silhouette: tuple[tuple[float, float], ...]
    connections: tuple[Connection, ...] = ()
    pad_width: int = 0

    def land_neighbors(self) -> Iterable[str]:
        return (c.neighbor_id for c in self.connections if c.kind != "boat")


@dataclass(frozen=True)
class World:
    size: Size
    projection: str  # e.g. "top_down" | "oblique" — first-class, enforced in prompts
    outside_color: tuple[int, int, int, int]
    levels: dict[str, Level] = field(default_factory=dict)

    def level(self, level_id: str) -> Level:
        return self.levels[level_id.zfill(2)]


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #
class LevelState(str, Enum):
    PREPARED = "prepared"
    READY = "ready"
    GENERATING = "generating"
    GENERATED = "generated"
    QA_PASSED = "qa_passed"
    QA_FAILED = "qa_failed"
    ACCEPTED = "accepted"
    FAILED = "failed"


# Allowed transitions. `reset` is modeled separately (it can jump from any state
# back to READY) so it is intentionally not in this table.
_TRANSITIONS: dict[LevelState, frozenset[LevelState]] = {
    LevelState.PREPARED: frozenset({LevelState.READY}),
    LevelState.READY: frozenset({LevelState.GENERATING}),
    LevelState.GENERATING: frozenset({LevelState.GENERATED, LevelState.FAILED}),
    LevelState.GENERATED: frozenset({LevelState.QA_PASSED, LevelState.QA_FAILED}),
    LevelState.QA_PASSED: frozenset({LevelState.ACCEPTED, LevelState.READY}),
    LevelState.QA_FAILED: frozenset({LevelState.READY}),
    LevelState.ACCEPTED: frozenset(),  # terminal (except via reset)
    LevelState.FAILED: frozenset({LevelState.READY}),
}


def can_transition(current: LevelState, target: LevelState) -> bool:
    return target in _TRANSITIONS.get(current, frozenset())


def assert_transition(current: LevelState, target: LevelState) -> None:
    if not can_transition(current, target):
        raise ValueError(f"illegal state transition: {current.value} -> {target.value}")
