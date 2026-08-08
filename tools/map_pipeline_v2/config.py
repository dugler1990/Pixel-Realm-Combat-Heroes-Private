"""Layered configuration schema + loader.

Config is grouped by concern (world / generation / prompt / continuity / conform /
qa / execution / observability) so each pipeline layer reads only its own slice.
`load_config` merges a user file over the built-in defaults and returns a resolved,
frozen object; `to_dict` snapshots it (write this next to each run as
`config.resolved.json`).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorldConfig:
    width: int = 512
    height: int = 384
    projection: str = "top_down"
    outside_color: tuple[int, int, int, int] = (0, 0, 0, 255)


@dataclass(frozen=True)
class GenerationConfig:
    provider: str = "copy"           # registered backend name
    operation: str = "reference_guided"
    model: str = ""
    strength: str = "HIGH"
    reference_encoding: str = "png"  # png (lossless, sharp silhouette) | jpeg
    seed: int | None = None
    candidates: int = 1
    extra: dict[str, Any] = field(default_factory=dict)  # provider-specific knobs


@dataclass(frozen=True)
class PromptConfig:
    seed_template: str = "seed"
    pad_template: str = "pad"        # NB: the short 003-style continuity, not the A/B essay
    style_prompt: str = (
        "Top-down fantasy RPG albedo map art. Diffuse shadow-neutral lighting; "
        "local form shading only, no directional cast shadows."
    )
    negatives: tuple[str, ...] = ("labels", "text", "UI", "grid", "border", "characters")


@dataclass(frozen=True)
class ContinuityConfig:
    pad_width: int = 32
    feather_radius: int = 6
    seam_blend: str = "feather"      # feather | hard


@dataclass(frozen=True)
class ConformConfig:
    strategy: str = "auto"           # auto | identity | crop | warp
    overflow_area_ratio: float = 1.25  # content/mask area above this => treat as full-frame => crop
    warp_min_iou: float = 0.90       # only warp when already this close


@dataclass(frozen=True)
class QaConfig:
    min_iou: float = 0.97
    max_area_ratio: float = 1.05     # after conform, content must sit inside the shape
    black_purity_tol: int = 6        # max mean luma allowed outside the silhouette
    max_seam_delta: float = 24.0     # mean edge delta across the pad boundary


@dataclass(frozen=True)
class ExecutionConfig:
    approval_mode: str = "auto_if_pass"  # manual | auto_if_pass (never "accept whatever")
    retry_limit: int = 2
    retry_strategy: str = "reseed"       # reseed | prompt_variant | none
    stop_on_failure: bool = True
    concurrency: int = 1


@dataclass(frozen=True)
class ObservabilityConfig:
    log_level: str = "info"
    keep_raw: bool = True
    html_report: bool = True


@dataclass(frozen=True)
class Config:
    world: WorldConfig = field(default_factory=WorldConfig)
    generation: GenerationConfig = field(default_factory=GenerationConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    continuity: ContinuityConfig = field(default_factory=ContinuityConfig)
    conform: ConformConfig = field(default_factory=ConformConfig)
    qa: QaConfig = field(default_factory=QaConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SECTIONS: dict[str, type] = {
    "world": WorldConfig,
    "generation": GenerationConfig,
    "prompt": PromptConfig,
    "continuity": ContinuityConfig,
    "conform": ConformConfig,
    "qa": QaConfig,
    "execution": ExecutionConfig,
    "observability": ObservabilityConfig,
}


def _coerce_section(section_cls: type, raw: dict[str, Any]) -> Any:
    """Build a frozen section from a dict, ignoring unknown keys (forward-compat)."""
    valid = {f for f in section_cls.__dataclass_fields__}  # type: ignore[attr-defined]
    kwargs = {k: v for k, v in raw.items() if k in valid}
    # normalize list -> tuple for frozen tuple fields
    for key, value in list(kwargs.items()):
        if isinstance(value, list):
            kwargs[key] = tuple(value)
    return section_cls(**kwargs)


def from_dict(data: dict[str, Any]) -> Config:
    sections: dict[str, Any] = {}
    for name, cls in _SECTIONS.items():
        raw = data.get(name) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"config section {name!r} must be an object")
        sections[name] = _coerce_section(cls, raw)
    return Config(**sections)


def load_config(path: str | Path | None) -> Config:
    if path is None:
        return Config()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return from_dict(data)


def snapshot_config(config: Config, dest: str | Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
    return dest
