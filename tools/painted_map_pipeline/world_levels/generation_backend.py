from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from ..image_client import make_image_client
from .models import ContextImage, GenerationJob
from .state_store import read_json

Image.MAX_IMAGE_PIXELS = None


def job_context_images(job: GenerationJob) -> list[ContextImage]:
    """The roster this job was built with, in the order its prompt numbers.

    Read back from ``job.json`` rather than re-derived: the renderer produced the roster and
    the prompt together, so reconstructing it here from a module-level list is exactly the
    drift the numbering is meant to be immune to.
    """
    manifest = read_json(job.manifest_path)
    return [ContextImage.from_dict(item) for item in manifest.get("context", [])]


def job_context_paths(job: GenerationJob) -> list[str]:
    return [str(job.directory / item.filename) for item in job_context_images(job)]


def job_generation_size(job: GenerationJob) -> tuple[int, int] | None:
    manifest = read_json(job.manifest_path)
    size = manifest.get("input_size")
    return (int(size[0]), int(size[1])) if size else None


class GenerationBackend:
    def generate(self, job: GenerationJob) -> Path | None:
        raise NotImplementedError


def job_seed(config: dict[str, Any], job: GenerationJob) -> int | None:
    """Deterministic per-attempt seed so any attempt can be replayed exactly.

    ``seed_base`` fixes the series; the attempt number varies the draw, so a run of
    N attempts is a reproducible sample rather than N unrecorded coin flips. An
    explicit ``seed`` pins every attempt to one draw. Neither set means unseeded.
    """
    if config.get("seed") is not None:
        return int(config["seed"])
    base = config.get("seed_base")
    if base is None:
        return None
    return int(base) + int(job.attempt)


class ImageClientBackend(GenerationBackend):
    def __init__(self, config: dict[str, Any]):
        self.config = dict(config)

    def generate(self, job: GenerationJob) -> Path | None:
        prompt = job.prompt_path.read_text(encoding="utf-8")
        references = job_context_paths(job)
        if not references:
            raise ValueError(f"job {job.directory} has no context images to send")

        # Rebuild the client per attempt: the seed is part of the request, and so is the
        # size, which is per level under the frame renderer rather than one canvas for all.
        config = dict(self.config)
        seed = job_seed(config, job)
        if seed is not None:
            config["seed"] = seed
        size = job_generation_size(job)
        if size is not None:
            config["width"], config["height"] = size
        client = make_image_client(config)

        # No mask. Masked editing hides the region under the mask from the model, so
        # masking the land asks it to invent terrain it cannot see -- measured on level
        # 03, that returns a black frame with only the unmasked padding surviving. The
        # images go in as labelled references instead, and the silhouette is enforced by
        # the mask picture in the roster plus the composite at ingest.
        mask = None

        result_path = job.directory / "generation_result.json"
        try:
            result = client.generate(prompt, references, str(job.output_path), mask=mask)
        except Exception as exc:
            result_path.write_text(
                json.dumps(
                    {"level_id": job.level_id, "attempt": job.attempt, "seed": seed, "error": str(exc)},
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            raise

        result = dict(result)
        result.update({"level_id": job.level_id, "attempt": job.attempt, "seed": seed})
        output = Path(str(result.get("output_path") or job.output_path))
        if output.is_file():
            with Image.open(output) as image:
                returned_size = list(image.size)
            result["returned_size"] = returned_size
            requested = result.get("generation_size")
            if requested and returned_size != list(requested):
                # Leonardo silently rescales; record it rather than letting it pass unnoticed.
                result["size_mismatch"] = True
        result_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        return output if output.is_file() else None


def make_generation_backend(config: dict[str, Any]) -> GenerationBackend:
    return ImageClientBackend(config)
