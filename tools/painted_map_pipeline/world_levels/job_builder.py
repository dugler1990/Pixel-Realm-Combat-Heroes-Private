from __future__ import annotations

from pathlib import Path

from PIL import Image

from .config import load_config
from .frames import Frame
from .plan_loader import load_level_plan
from .models import GenerationJob, LevelState
from .package_builder import level_paths
from .renderers import RequestContext, get_renderer, load_image
from .renderers.base import (
    Request,
    annotation_context,
    ascii_prompt,
    retry_context,
    roster_lines,
)
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


# Every rejected attempt goes back, not just the last: a model that already tried twice needs
# to see both, or it re-makes the mistake it was told about two attempts ago. Older ones are
# thumbnailed -- their job is to say "not this either", which does not need full resolution --
# and the list is capped so the roster stays inside the provider's image limit.
RETRY_HISTORY = 4
RETRY_THUMBNAIL = 1024
_ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth")


def _rejection_note(attempt_dir: Path) -> str:
    note = attempt_dir / "rejection.txt"
    return note.read_text(encoding="utf-8").strip() if note.is_file() else ""


ATTACHMENT_THUMBNAIL = 1536


def _with_retry_context(
    root: Path,
    level_id: str,
    request,
    reason: str,
    attachment: tuple[Path, str] | None = None,
):
    """Add every rejected attempt as a further image, each with what was wrong with it.

    Everything the renderer built is kept -- the retry sees the same inputs it saw the first
    time. The reason is whatever was typed at the review prompt; the automatic checks are a
    separate, opt-in command, so their output only reaches the model if a person puts it here.

    The reason is also written beside the attempt it criticises, which is what makes the
    history survive: on the next retry that note is read back and sent again.
    """
    reason = (reason or "").strip()
    paths = level_paths(root, level_id)
    attempts = sorted(paths["root"].glob("attempts/attempt_*/generated.raw.png"))
    if not attempts or not (reason or attachment):
        return request

    if reason:
        # The reason just typed is about the newest attempt, so record it there before
        # collecting: that note is what makes the history survive into later retries.
        (attempts[-1].parent / "rejection.txt").write_text(reason + "\n", encoding="utf-8")

    history = [(path, _rejection_note(path.parent)) for path in attempts]
    history = [item for item in history if item[1]][-RETRY_HISTORY:]
    if not history and not attachment:
        return request

    images = list(request.images)
    lines = [request.prompt.rstrip(), ""]
    if len(history) > 1:
        lines.append(f"You have tried this {len(history)} times and each attempt was rejected.")
    for position, (path, note) in enumerate(history):
        attempt_number = int(path.parent.name.split("_")[1])
        ordinal = _ORDINALS[min(position, len(_ORDINALS) - 1)]
        with Image.open(path) as opened:
            image = opened.convert("RGBA")
        if path is not history[-1][0]:
            # Older attempts are context, not the thing being corrected.
            image.thumbnail((RETRY_THUMBNAIL, RETRY_THUMBNAIL))
        item = retry_context(attempt_number, ordinal)
        images.append((item, image))
        lines.append(f"Image {len(images)} is your {ordinal} attempt. It was rejected because:")
        lines.append(note)
    if attachment is not None:
        # One-shot, unlike the rejection notes: it answers "look at this, for this retry".
        # Thumbnailed because what it shows is a large-scale error, not fine detail.
        path, note = attachment
        with Image.open(path) as opened:
            extra = opened.convert("RGBA")
        extra.thumbnail((ATTACHMENT_THUMBNAIL, ATTACHMENT_THUMBNAIL))
        images.append((annotation_context(f"attached_{path.name}", note), extra))
        lines.append(f"Image {len(images)}: {note}")
    lines += [
        "",
        "Try again from the same inputs, using your most recent attempt as the starting",
        "point, and fix everything named above - including what was wrong with the earlier",
        "attempts. Everything else about it was right; change nothing else.",
    ]
    return Request(images=tuple(images), prompt=ascii_prompt(lines), size=request.size)


def create_job(
    root: str | Path,
    level_id: str,
    prompt_file: str | Path | None = None,
    *,
    refine: bool = False,
    retry_reason: str | None = None,
    retry_image: str | Path | None = None,
    retry_note: str = "",
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

    # Whole adjacent levels as context: accepted art where a neighbour is finished, its soft
    # template otherwise. Downscaled -- they are for orientation, never copied pixel for pixel.
    neighbours: list[tuple[str, str, Image.Image, str]] = []
    try:
        plan = load_level_plan(config.level_plan)
        centre = lambda spec: (
            sum(p[0] for p in spec.core_polygon) / len(spec.core_polygon),
            sum(p[1] for p in spec.core_polygon) / len(spec.core_polygon),
        )
        cx, cy = centre(plan[level_id])
        for connection in plan[level_id].connections:
            other = level_paths(root_path, connection.level_id)
            accepted = other["root"] / "accepted" / "image.png"
            source, status = (accepted, "finished") if accepted.is_file() else (other["dense_template"], "rough")
            if not Path(source).is_file():
                continue
            image = load_image(source)
            image.thumbnail((1024, 1024))
            ox, oy = centre(plan[connection.level_id])
            if abs(ox - cx) >= abs(oy - cy):
                direction = "west" if ox < cx else "east"
            else:
                direction = "north" if oy < cy else "south"
            neighbours.append((connection.level_id, status, image, direction))
    except Exception:  # context is a bonus; never fail a job over it
        neighbours = []

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
        neighbours=tuple(neighbours),
        # Decided by the generation config but needed here: it governs the renderer's guards,
        # not just what the backend attaches to the request.
        mask_holds_the_shape=bool(config.generation.get("mask_edits")),
        single_image=bool(config.generation.get("single_image")),
    )
    # Certain failures are caught here, before any file is written or any call is made.
    renderer.preflight(context)
    request = renderer.request(context)
    # A retry that starts cold repeats the same mistake. Appending the rejected attempt and
    # the reason costs one image and a sentence, and it goes on the end so the roster
    # numbering the renderer already wrote stays correct.
    if retry_reason is not None:
        attachment = (Path(retry_image), retry_note) if retry_image else None
        request = _with_retry_context(root_path, level_id, request, retry_reason, attachment)
    for item, image in request.images:
        image.save(job_dir / item.filename)
    for name in CANVAS_ASSETS:
        with Image.open(paths[name]) as opened:
            opened.save(canvas_asset(job_dir, name))

    prompt_path = job_dir / "prompt.txt"
    if prompt_file:
        # Hand-written prompt: the wording is iterated without editing a renderer. Only the
        # generated body is discarded -- the roster still goes in front of it, because it is
        # built per level from the images actually being sent and is the only thing naming the
        # silhouette to fill and whether a padding image is present at all.
        roster = roster_lines([item for item, _ in request.images])
        body = Path(prompt_file).expanduser().resolve().read_text(encoding="utf-8")
        prompt_text = ascii_prompt(roster + [body])
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
