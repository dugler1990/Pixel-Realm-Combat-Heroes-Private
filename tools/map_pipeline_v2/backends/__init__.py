"""Backend registry + factory.

Register a backend with `@register_backend("name")`; build one from config with
`make_backend(config)`. Adding a provider requires no pipeline changes — just an
adapter module imported here so its decorator runs.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .base import (
    BackendCapabilities,
    GenerationBackend,
    GenerationRequest,
    GenerationResult,
    Operation,
)

_REGISTRY: dict[str, Callable[[Mapping[str, Any]], GenerationBackend]] = {}


def register_backend(name: str) -> Callable[[type], type]:
    def decorator(cls: type) -> type:
        if name in _REGISTRY:
            raise ValueError(f"backend already registered: {name!r}")
        cls.name = name  # type: ignore[attr-defined]
        _REGISTRY[name] = lambda config: cls(config)  # type: ignore[call-arg]
        return cls

    return decorator


def available_backends() -> list[str]:
    return sorted(_REGISTRY)


def make_backend(config: Mapping[str, Any]) -> GenerationBackend:
    provider = str(config.get("provider") or "copy").strip().lower()
    if provider not in _REGISTRY:
        raise ValueError(
            f"unknown backend {provider!r}; available: {', '.join(available_backends())}"
        )
    return _REGISTRY[provider](config)


# Import adapter modules so their @register_backend decorators run.
from . import copy as _copy  # noqa: E402,F401  (key-free backends: copy/dryrun/overflow_demo)

__all__ = [
    "BackendCapabilities",
    "GenerationBackend",
    "GenerationRequest",
    "GenerationResult",
    "Operation",
    "register_backend",
    "make_backend",
    "available_backends",
]
