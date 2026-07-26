from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


Point = tuple[int, int]


class LevelState(str, Enum):
    UNPREPARED = "unprepared"
    PREPARED = "prepared"
    READY = "ready"
    GENERATING = "generating"
    GENERATED = "generated"
    ACCEPTED = "accepted"
    FAILED = "failed"


@dataclass(frozen=True)
class Connection:
    level_id: str
    kind: str = "land"


@dataclass(frozen=True)
class LevelSpec:
    level_id: str
    name: str
    region: str
    crop_x: int
    crop_y: int
    crop_width: int
    crop_height: int
    overlap_buffer: int
    core_polygon: tuple[Point, ...]
    generation_polygon: tuple[Point, ...]
    connections: tuple[Connection, ...]

    @property
    def crop_box(self) -> tuple[int, int, int, int]:
        return (
            self.crop_x,
            self.crop_y,
            self.crop_x + self.crop_width,
            self.crop_y + self.crop_height,
        )

    def connection_to(self, level_id: str) -> Connection | None:
        return next((item for item in self.connections if item.level_id == level_id), None)


@dataclass(frozen=True)
class CanvasConfig:
    mode: str
    width: int | None
    height: int | None
    placement: str
    margin: int


@dataclass(frozen=True)
class ExecutionConfig:
    approval_mode: str = "manual"
    stop_on_failure: bool = True
    retry_limit: int = 2


@dataclass(frozen=True)
class RunConfig:
    config_path: Path
    world_map: Path
    level_plan: Path
    output_root: Path
    scale: str
    canvas: CanvasConfig
    outside_color: tuple[int, int, int, int]
    source_resampling: str
    execution: ExecutionConfig
    generation: dict[str, Any] = field(default_factory=dict)
    style_prompt: str = ""
    review_overlay: Path | None = None


@dataclass(frozen=True)
class LevelTransform:
    scale: str
    scaled_crop_left: int
    scaled_crop_top: int
    scaled_crop_width: int
    scaled_crop_height: int
    canvas_offset_x: int
    canvas_offset_y: int
    canvas_width: int
    canvas_height: int

    def global_to_local(self, x: int, y: int) -> Point:
        return (
            x - self.scaled_crop_left + self.canvas_offset_x,
            y - self.scaled_crop_top + self.canvas_offset_y,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "scale": self.scale,
            "scaled_crop_origin": [self.scaled_crop_left, self.scaled_crop_top],
            "scaled_crop_size": [self.scaled_crop_width, self.scaled_crop_height],
            "canvas_offset": [self.canvas_offset_x, self.canvas_offset_y],
            "canvas_size": [self.canvas_width, self.canvas_height],
        }


@dataclass(frozen=True)
class OverlapRaster:
    global_box: tuple[int, int, int, int]
    pixels: Any

    @property
    def width(self) -> int:
        return self.global_box[2] - self.global_box[0]

    @property
    def height(self) -> int:
        return self.global_box[3] - self.global_box[1]


@dataclass(frozen=True)
class GenerationJob:
    level_id: str
    attempt: int
    directory: Path
    input_path: Path
    prompt_path: Path
    output_path: Path
    manifest_path: Path
