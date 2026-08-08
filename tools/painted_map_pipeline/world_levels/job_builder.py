from __future__ import annotations

from pathlib import Path

from PIL import Image

from .config import load_config
from .frames import Frame
from .models import GenerationJob, LevelState
from .package_builder import level_paths
from .renderers import RequestContext, get_renderer, load_image
from .state_store import append_event, atomic_write_json, read_json, sha256_file, utc_now

# Canvas-space assets the ingest path needs whatever was sent. They live in a subdirectory
# because a renderer's roster may contain a same-named image at a different size -- the frame
# renderer sends a crop of locked_overlap.png, while the hard paste still needs the whole
# canvas. Top level is what went to the model; canvas/ is what the pipeline reads back.
CANVAS_ASSETS = ("generation_mask", "locked_pixels", "locked_mask", "pending_mask")
CANVAS_FILENAMES = {
    "generation_mask": "generation_mask.png",
    "locked_pixels": "locked_overlap.png",
    "locked_mask": "locked_overlap_mask.png",
    "pending_mask": "pending_mask.png",
}


def canvas_asset(job_dir: Path, name: str) -> Path:
    return job_dir / "canvas" / CANVAS_FILENAMES[name]


def create_job(
    root: str | Path,
    level_id: str,
    prompt_file: str | Path | None = None,
    *,
    refine: bool = False,
) -> GenerationJob:
    root_path = Path(root).resolve()
    config = load_config(root_path / "config.resolved.json")
    run = read_json(root_path / "run.json")
    level_id = level_id.zfill(2)
    state = run["levels"][level_id]["state"]
    allowed = {LevelState.PREPARED.value, LevelState.READY.value, LevelState.FAILED.value}
    if refine:
        # A refine pass is a second run over finished art, so accepted is the expected
        # starting state rather than an error.
        allowed.add(LevelState.ACCEPTED.value)
    if state not in allowed:
        raise ValueError(f"level {level_id} cannot create a job from state {state!r}")
    paths = level_paths(root_path, level_id)
    manifest = read_json(paths["manifest"])
    attempt = int(manifest.get("attempt_count", 0)) + 1
    job_dir = paths["root"] / "jobs" / f"attempt_{attempt:03d}"
    if job_dir.exists():
        raise FileExistsError(f"job attempt already exists: {job_dir}")
    (job_dir / "canvas").mkdir(parents=True)

    renderer = get_renderer(config.renderer)
    context = RequestContext(
        level_id=level_id,
        canvas_size=tuple(int(value) for value in manifest["canvas_size"]),
        frame=Frame.from_dict(manifest["frame"]),
        outside_color=config.outside_color,
        generation_input=load_image(paths["generation_input"]),
        generation_mask=load_image(paths["generation_mask"], "L"),
        locked_pixels=load_image(paths["locked_pixels"]),
        locked_mask=load_image(paths["locked_mask"], "L"),
        locator=load_image(paths["locator"]),
        style_prompt=config.style_prompt,
        manifest=manifest,
        refine=refine,
    )
    request = renderer.request(context)
    for item, image in request.images:
        image.save(job_dir / item.filename)
    for name in CANVAS_ASSETS:
        with Image.open(paths[name]) as opened:
            opened.save(canvas_asset(job_dir, name))

    prompt_path = job_dir / "prompt.txt"
    if prompt_file:
        # Hand-written prompt: sent verbatim, so wording can be iterated without editing a
        # renderer. The generated one is discarded, the roster it was built from is not.
        prompt_text = Path(prompt_file).expanduser().resolve().read_text(encoding="utf-8")
    else:
        prompt_text = request.prompt
    prompt_path.write_text(prompt_text, encoding="utf-8")

    job_manifest = {
        "schema_version": 2,
        "level_id": level_id,
        "attempt": attempt,
        "state": LevelState.READY.value,
        "created_at": utc_now(),
        "context_revision": manifest["context_revision"],
        "renderer": renderer.name,
        "frame": manifest["frame"],
        "canvas_size": manifest["canvas_size"],
        "input_size": list(request.size),
        "context": [item.as_dict() for item, _ in request.images],
        "input_hash": sha256_file(job_dir / "input.png"),
        "generation_mask_hash": sha256_file(canvas_asset(job_dir, "generation_mask")),
        "locked_mask_hash": sha256_file(canvas_asset(job_dir, "locked_mask")),
        "locked_pixels_hash": sha256_file(canvas_asset(job_dir, "locked_pixels")),
        "neighbor_sources": manifest.get("locked_sources", []),
        "output_path": str(job_dir / "generated.png"),
        "refine": refine,
    }
    atomic_write_json(job_dir / "job.json", job_manifest)
    manifest.update(
        {
            "attempt_count": attempt,
            "latest_job": str(job_dir / "job.json"),
            "state": LevelState.READY.value,
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(paths["manifest"], manifest)
    run["levels"][level_id].update(
        {
            "state": LevelState.READY.value,
            "attempt_count": attempt,
            "latest_job": str(job_dir / "job.json"),
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(root_path / "run.json", run)
    append_event(root_path, "job_created", level_id=level_id, attempt=attempt)
    return GenerationJob(
        level_id=level_id,
        attempt=attempt,
        directory=job_dir,
        input_path=job_dir / "input.png",
        prompt_path=prompt_path,
        output_path=job_dir / "generated.png",
        manifest_path=job_dir / "job.json",
    )
