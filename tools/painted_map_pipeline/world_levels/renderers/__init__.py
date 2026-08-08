"""Rendering methods, and the only place in the pipeline that names one."""

from __future__ import annotations

from .base import (
    FootprintRejected,
    PlaceContext,
    Renderer,
    Request,
    RequestContext,
    load_image,
)
from .frame import FrameRenderer
from .warp import WarpRenderer

_RENDERERS = {renderer.name: renderer for renderer in (WarpRenderer(), FrameRenderer())}


def get_renderer(name: str) -> Renderer:
    try:
        return _RENDERERS[str(name).strip().lower()]
    except KeyError:
        raise ValueError(
            f"unknown renderer {name!r}; expected one of {', '.join(sorted(_RENDERERS))}"
        ) from None


__all__ = [
    "FootprintRejected",
    "FrameRenderer",
    "PlaceContext",
    "Renderer",
    "Request",
    "RequestContext",
    "WarpRenderer",
    "get_renderer",
    "load_image",
]
