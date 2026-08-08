"""Backend contract — the provider-agnostic generation interface.

The pipeline speaks only this contract; each provider (Leonardo, gpt-image, Gemini,
future models) is an adapter that maps a `GenerationRequest` onto its own API. The
crucial field is `BackendCapabilities.enforces_region`: it tells the pipeline
whether the frozen region (pad + outside black) is guaranteed by construction
(mask-locked edit) or merely suggested (soft reference). Conform + QA strategy are
chosen from that flag, so swapping backends can never silently melt a tile.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from ..models import ImageRef, MaskRef, Size


class Operation(str, Enum):
    EDIT_MASKED = "edit_masked"          # paint only inside paint_mask; freeze the rest
    REFERENCE_GUIDED = "reference_guided"  # fresh generation guided by canvas as a reference
    STRUCTURAL = "structural"            # ControlNet / structural conditioning
    TXT2IMG = "txt2img"                  # prompt only


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    canvas: ImageRef                     # composed input (pad baked, placeholder inside)
    paint_mask: MaskRef                  # where the model MAY paint (pending region)
    freeze_mask: MaskRef | None          # pixels that MUST survive (pad + outside black)
    size: Size
    operation: Operation = Operation.REFERENCE_GUIDED
    seed: int | None = None
    params: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationResult:
    image_path: Path                     # the raw model output on disk
    provider: str
    metadata: Mapping[str, Any] = field(default_factory=dict)  # request id, seed used, cost…


@dataclass(frozen=True)
class BackendCapabilities:
    enforces_region: bool                # True => freeze_mask honored by construction
    accepts_mask: bool
    max_refs: int
    native_size: Size | None
    supports_seed: bool
    operations: tuple[Operation, ...] = ()


class GenerationBackend(ABC):
    """Base class for all generation backends. Adapters stay tiny; retries,
    logging and artifact capture live in GenerationService, not here."""

    name: str = "base"

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        self.config = dict(config or {})

    @abstractmethod
    def capabilities(self) -> BackendCapabilities:  # pragma: no cover - interface
        ...

    def validate_config(self) -> list[str]:
        """Return a list of human-readable problems (empty == OK). Override to
        check API keys, required params, size limits before a run starts."""
        return []

    @abstractmethod
    def generate(self, request: GenerationRequest, *, workdir: Path) -> GenerationResult:  # pragma: no cover
        """Produce a raw image for `request`, writing into `workdir`."""
        ...
