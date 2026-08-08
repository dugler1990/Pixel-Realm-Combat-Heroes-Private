"""Key-free backends for developing and testing the loop without an API.

- `copy`          — echoes the composed canvas back as the "generation". Because
                    output == input (already masked to the silhouette), the frozen
                    region trivially survives, so it declares enforces_region=True.
- `dryrun`        — writes the request as JSON and produces no image (planning).
- `overflow_demo` — deliberately paints the whole frame white, ignoring the
                    silhouette. Declares enforces_region=False so the pipeline must
                    crop-and-gate: this reproduces the v1 full-frame melt and proves
                    conform/QA catch it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from PIL import Image

from . import register_backend
from .base import (
    BackendCapabilities,
    GenerationBackend,
    GenerationRequest,
    GenerationResult,
    Operation,
)

Image.MAX_IMAGE_PIXELS = None


@register_backend("copy")
class CopyBackend(GenerationBackend):
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            enforces_region=True,
            accepts_mask=True,
            max_refs=1,
            native_size=None,
            supports_seed=False,
            operations=(Operation.EDIT_MASKED, Operation.REFERENCE_GUIDED),
        )

    def generate(self, request: GenerationRequest, *, workdir: Path) -> GenerationResult:
        src = Path(request.canvas.path)
        if not src.is_file():
            raise FileNotFoundError(f"canvas image does not exist: {src}")
        out = Path(workdir) / "raw.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out)
        return GenerationResult(image_path=out, provider=self.name, metadata={"echo": True})


@register_backend("dryrun")
class DryRunBackend(GenerationBackend):
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            enforces_region=False,
            accepts_mask=False,
            max_refs=1,
            native_size=None,
            supports_seed=False,
        )

    def generate(self, request: GenerationRequest, *, workdir: Path) -> GenerationResult:
        out = Path(workdir) / "request.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "prompt": request.prompt,
                    "operation": request.operation.value,
                    "canvas": str(request.canvas.path),
                    "size": request.size.as_tuple(),
                    "seed": request.seed,
                    "params": dict(request.params),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        # No image is produced; the pipeline treats this as "awaiting external image".
        return GenerationResult(image_path=out, provider=self.name, metadata={"dry_run": True})


@register_backend("overflow_demo")
class SyntheticOverflowBackend(GenerationBackend):
    """Paints the entire frame, ignoring the silhouette — a stand-in for a soft
    reference model that fills the rectangle. Used to exercise crop + QA."""

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            enforces_region=False,
            accepts_mask=False,
            max_refs=1,
            native_size=None,
            supports_seed=True,
            operations=(Operation.REFERENCE_GUIDED,),
        )

    def generate(self, request: GenerationRequest, *, workdir: Path) -> GenerationResult:
        w, h = request.size.as_tuple()
        img = Image.new("RGBA", (w, h), (230, 235, 245, 255))  # full-frame "map"
        out = Path(workdir) / "raw.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
        return GenerationResult(image_path=out, provider=self.name, metadata={"full_frame": True})
