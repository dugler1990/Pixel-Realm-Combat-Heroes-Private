from __future__ import annotations

from pathlib import Path
from typing import Any

from ..image_client import make_image_client
from .models import GenerationJob

# Job-folder context package (same files an agent would open).
CONTEXT_IMAGE_NAMES = (
    "input.png",
    "locked_overlap.png",
    "generation_mask.png",
    "pending_mask.png",
    "locator.png",
)


def job_context_images(job: GenerationJob) -> list[str]:
    paths: list[str] = []
    for name in CONTEXT_IMAGE_NAMES:
        path = job.directory / name
        if path.is_file():
            paths.append(str(path))
    return paths


class GenerationBackend:
    def generate(self, job: GenerationJob) -> Path | None:
        raise NotImplementedError


class ImageClientBackend(GenerationBackend):
    def __init__(self, config: dict[str, Any]):
        self.config = dict(config)
        self.client = make_image_client(self.config)

    def generate(self, job: GenerationJob) -> Path | None:
        prompt = job.prompt_path.read_text(encoding="utf-8")
        references = job_context_images(job)
        if not references:
            raise ValueError(f"job {job.directory} has no context images to send")
        result = self.client.generate(prompt, references, str(job.output_path))
        output = Path(str(result.get("output_path") or job.output_path))
        return output if output.is_file() else None


def make_generation_backend(config: dict[str, Any]) -> GenerationBackend:
    return ImageClientBackend(config)
