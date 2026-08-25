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
    # Rescale a generation onto the template bbox when its raw land footprint matches
    # generation_mask.png worse than this. 0 disables the rescale entirely.
    rescale_below_iou: float = 0.0


@dataclass(frozen=True)
class SplitConfig:
    """Settings for the chunk -> sub-level splitter (the `split` command).

    ``buckets`` maps chunk core-polygon area to a sub-level count: an ascending list of
    ``(upper_exclusive_area, count)``; an area at or above the last threshold uses
    ``default_count``. The result is clamped to ``[min_sublevels, max_sublevels]``.
    ``proposer`` is a make_image_client-style dict (provider/model/api_key_env) for the
    region-proposal call.
    """

    buckets: tuple[tuple[float, int], ...] = (
        (24000.0, 2),
        (40000.0, 3),
        (52000.0, 4),
        (62000.0, 5),
    )
    default_count: int = 6
    min_sublevels: int = 2
    max_sublevels: int = 6
    overlap_buffer_px: int = 8
    crop_margin_px: int = 4
    smooth_kernel: int = 3        # majority-filter kernel applied to the partition before vectorizing
    simplify_tolerance: float = 2.0  # Douglas-Peucker distance (px) for de-staircasing borders
    criteria: str = ""  # optional extra instruction appended to the proposer prompt
    proposer: dict[str, Any] = field(default_factory=dict)

    def count_for_area(self, area: float) -> int:
        chosen = self.default_count
        for upper, count in self.buckets:
            if area < upper:
                chosen = count
                break
        return max(self.min_sublevels, min(self.max_sublevels, chosen))


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
    split: "SplitConfig | None" = None

    @property
    def renderer(self) -> str:
        """Which renderer this run was prepared for. Validated in ``parse_config``."""
        return str(self.generation.get("renderer") or "warp").strip().lower()


@dataclass(frozen=True)
class ContextImage:
    """One reference image and the job it does.

    The API has no per-image caption, so position in the list is the only label the model
    gets. A renderer builds its roster and its prompt together from this, so the numbering
    in the text cannot drift away from the pictures that arrive.
    """

    filename: str
    role: str
    description: str

    def as_dict(self) -> dict[str, Any]:
        return {"filename": self.filename, "role": self.role, "description": self.description}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ContextImage":
        return cls(str(value["filename"]), str(value["role"]), str(value["description"]))


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
