from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from .config import load_config
from .frames import Frame
from .job_builder import canvas_asset
from .models import LevelState
from .package_builder import level_paths
from .renderers import FootprintRejected, PlaceContext, get_renderer, load_image
from .state_store import append_event, atomic_write_json, read_json, sha256_file, utc_now

Image.MAX_IMAGE_PIXELS = None

__all__ = ["FootprintRejected", "accept_result", "ingest_result", "unaccept_result"]


def _job_for_attempt(paths: dict[str, Path], attempt: int | None) -> tuple[Path, dict[str, Any]]:
    manifest = read_json(paths["manifest"])
    if attempt is None:
        latest = manifest.get("latest_job")
        if not latest:
            raise ValueError("level has no generation job")
        job_path = Path(latest)
    else:
        job_path = paths["root"] / "jobs" / f"attempt_{attempt:03d}" / "job.json"
    if not job_path.is_file():
        raise FileNotFoundError(f"generation job does not exist: {job_path}")
    return job_path, read_json(job_path)


def _select_padding(spec, locked_mask):
    """Whether to paste the neighbours' strips at all.

    Pasting is what makes two levels share identical pixels at their join. It also drops one
    level's rendering of a piece of ground on top of another's, and the two can disagree
    visibly even when their brightness and detail match -- so being able to re-place without
    it, and look, is the only way to tell the paste apart from a bad generation.

    Re-placing costs no API call, so this is free to toggle.
    """
    spec = (spec or "all").strip().lower()
    if spec == "none":
        return Image.new("L", locked_mask.size, 0), "none"
    return locked_mask, "all"


def _paste_padding_feathered(
    normalized, locked_pixels, locked_mask, pending_mask_image, feather: int
) -> None:
    """Paste the padding, fading it across the join so there is no hard line.

    The ramp spans the boundary rather than stopping at it: it reaches ``feather`` px into the
    padding on one side and ``feather`` px into the newly painted area on the other, so both
    sides move toward each other. Fading only inside the padding leaves the level's own
    terrain untouched, and a step between two untouched surfaces is still a step.

    The padding's far edge -- the side shared with the neighbour -- stays fully opaque, so
    those pixels remain byte-identical and the levels still tile.
    """
    import cv2
    import numpy as np

    locked = np.asarray(locked_mask, dtype=np.uint8) > 0
    pending = np.asarray(pending_mask_image, dtype=np.uint8) > 0
    if not locked.any() or not pending.any():
        normalized.paste(locked_pixels, (0, 0), locked_mask)
        return

    # Signed distance from the join: positive going into the padding, negative going into the
    # new art. Half weight exactly on the boundary, so neither side owns it.
    into_padding = cv2.distanceTransform((~pending).astype(np.uint8), cv2.DIST_L2, 3)
    into_new = cv2.distanceTransform((~locked).astype(np.uint8), cv2.DIST_L2, 3)
    signed = np.where(locked, into_padding, -into_new)
    alpha = np.clip(0.5 + signed / (2.0 * float(feather)), 0.0, 1.0)
    alpha = np.where(locked | pending, alpha, 0.0)

    base = np.asarray(normalized.convert("RGBA"), dtype=np.float32)
    over = np.asarray(locked_pixels.convert("RGBA"), dtype=np.float32)
    # Outside the padding there are no padding pixels to fade in, so carry its colour outward
    # by nearest neighbour -- that is what gives the new side something to blend toward.
    _, nearest = cv2.distanceTransformWithLabels(
        (~locked).astype(np.uint8), cv2.DIST_L2, 3, labelType=cv2.DIST_LABEL_PIXEL
    )
    ys, xs = np.where(locked)
    order = np.argsort(nearest[locked])
    lookup = np.zeros(nearest.max() + 1, dtype=np.int64)
    lookup[nearest[locked][order]] = (ys[order] * base.shape[1] + xs[order])
    flat = lookup[nearest]
    spread = over.reshape(-1, 4)[flat]
    over = np.where(locked[..., None], over, spread)

    blended = base * (1.0 - alpha[..., None]) + over * alpha[..., None]
    normalized.paste(Image.fromarray(blended.astype(np.uint8), "RGBA"), (0, 0))


def _next_placement(attempt_dir: Path, *, warped: bool) -> Path:
    """The next free output file for this attempt.

    The name says whether the warp ran, because that is the only thing that changes the
    geometry of what comes out: ``warp_normalize_NNN.png`` went through the fit onto the mask,
    ``placement_NNN.png`` is the generation with its padding pasted and nothing else done to
    it. Numbered so re-placing never destroys the version you were just comparing against.
    """
    stem = "warp_normalize" if warped else "placement"
    existing = sorted(attempt_dir.glob(f"{stem}_*.png"))
    return attempt_dir / f"{stem}_{len(existing) + 1:03d}.png"


def ingest_result(
    root: str | Path,
    level_id: str,
    image_path: str | Path,
    *,
    attempt: int | None = None,
    auto_accept: bool | None = None,
    feather: int = 0,
    fit_to_mask: bool = False,
    cut_to_mask: bool = False,
    padding: str = "all",
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    config = load_config(root_path / "config.resolved.json")
    run = read_json(root_path / "run.json")
    level_id = level_id.zfill(2)
    paths = level_paths(root_path, level_id)
    level_manifest = read_json(paths["manifest"])
    job_path, job = _job_for_attempt(paths, attempt)
    if job["level_id"] != level_id:
        raise ValueError("job level ID does not match ingestion level")
    if int(job["context_revision"]) != int(level_manifest["context_revision"]):
        raise ValueError("job context is stale; refresh and create a new job")
    if sha256_file(job_path.parent / "input.png") != job["input_hash"]:
        raise ValueError("job input hash no longer matches its manifest")

    source_path = Path(image_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"generated image does not exist: {source_path}")
    with Image.open(source_path) as opened:
        generated = opened.convert("RGBA")

    generation_mask = load_image(canvas_asset(job_path.parent, "generation_mask"), "L")
    locked_mask = load_image(canvas_asset(job_path.parent, "locked_mask"), "L")
    pending_path = canvas_asset(job_path.parent, "pending_mask")
    pending_mask_image = load_image(pending_path, "L") if pending_path.is_file() else None
    locked_pixels = load_image(canvas_asset(job_path.parent, "locked_pixels"))

    generation_result = job_path.parent / "generation_result.json"
    if generation_result.is_file():
        job["generation_result"] = read_json(generation_result)

    # The renderer recorded on the job, not the one in the live config: re-ingesting an old
    # attempt must normalize it under the rules it was generated for.
    renderer = get_renderer(job.get("renderer", "warp"))
    place_context = PlaceContext(
        level_id=level_id,
        canvas_size=tuple(int(value) for value in job["canvas_size"]),
        frame=Frame.from_dict(job["frame"]),
        outside_color=config.outside_color,
        generation_mask=generation_mask,
        locked_mask=locked_mask,
        sent_input=load_image(job_path.parent / "input.png"),
        rescale_below_iou=config.execution.rescale_below_iou,
        fit_to_mask=fit_to_mask,
        cut_to_mask=cut_to_mask,
        mask_holds_the_shape=bool(config.generation.get("mask_edits")),
    )
    try:
        normalized, info = renderer.place(generated, place_context)
    except FootprintRejected as exc:
        job["footprint_iou_raw"] = round(exc.footprint_iou, 4)
        job["footprint_iou"] = round(exc.footprint_iou, 4)
        # Only a first placement can fail the job. Re-placing an attempt that already produced
        # an image is an experiment -- toggling the warp on a level whose polygon fills the
        # canvas is refused by design -- and marking it failed threw away a good generation:
        # the next Enter could not accept it, because acceptance requires state 'generated'.
        if job.get("state") != LevelState.GENERATED.value:
            job["state"] = LevelState.FAILED.value
        atomic_write_json(job_path, job)
        append_event(
            root_path,
            "result_rejected",
            level_id=level_id,
            attempt=int(job["attempt"]),
            footprint_iou=job["footprint_iou"],
            reason=exc.reason,
        )
        raise
    job.update(info)

    # The one guarantee both renderers share, and the reason levels tile at all: the padding
    # comes back byte-identical from this job's own snapshot, whatever the model did to it.
    # Which neighbours' strips to paste. "all" (default) is the real behaviour; "none" leaves
    # the model's own art everywhere so the join can be judged without it; a list of neighbour
    # ids pastes only those. Each strip is the locked mask cut to that neighbour's recorded
    # global_box, so this needs no extra files -- job.json already says who contributed what.
    locked_mask, padding_note = _select_padding(padding, locked_mask)
    if feather and pending_mask_image is not None and padding_note != "none":
        _paste_padding_feathered(normalized, locked_pixels, locked_mask, pending_mask_image, feather)
    elif padding_note != "none":
        normalized.paste(locked_pixels, (0, 0), locked_mask)
    attempt_number = int(job["attempt"])
    attempt_dir = paths["root"] / "attempts" / f"attempt_{attempt_number:03d}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    raw_copy = attempt_dir / "generated.raw.png"
    if source_path != raw_copy:
        shutil.copy2(source_path, raw_copy)

    # One generation can be placed many times -- warp on or off, different feather widths --
    # and each is worth keeping: comparing them is the only way to tell whether a setting
    # helped, and a viewer handed the same path twice shows its cached copy.
    placement_path = _next_placement(attempt_dir, warped=bool(info.get("fit_to_mask")))
    normalized.save(placement_path)
    # One stable name for the newest version, whichever steps produced it. Everything that
    # just wants "the current image" reads this and never has to know how it was made.
    current_path = attempt_dir / "current.png"
    shutil.copy2(placement_path, current_path)

    job.update(
        {
            "state": LevelState.GENERATED.value,
            "ingested_at": utc_now(),
            "source_image": str(source_path),
            "raw_hash": sha256_file(source_path),
            "current_path": str(current_path),
            "placement_path": str(placement_path),
            "placement_feather": feather,
            "placement_padding": padding,
            "placement_fit_to_mask": fit_to_mask,
            "placement_cut_to_mask": cut_to_mask,
            "placement_hash": sha256_file(placement_path),
        }
    )
    atomic_write_json(job_path, job)
    level_manifest.update(
        {
            "state": LevelState.GENERATED.value,
            "latest_candidate": str(current_path),
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(paths["manifest"], level_manifest)
    run["levels"][level_id].update(
        {
            "state": LevelState.GENERATED.value,
            "latest_candidate": str(current_path),
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(root_path / "run.json", run)
    append_event(
        root_path,
        "result_ingested",
        level_id=level_id,
        attempt=attempt_number,
        placement_hash=job["placement_hash"],
        footprint_iou=job["footprint_iou"],
        footprint_iou_raw=job["footprint_iou_raw"],
        rescale_applied=job["rescale_applied"],
    )
    should_accept = config.execution.approval_mode == "automatic" if auto_accept is None else auto_accept
    if should_accept:
        return accept_result(root_path, level_id, attempt=attempt_number)
    return {
        "level_id": level_id,
        "attempt": attempt_number,
        "state": LevelState.GENERATED.value,
        # The numbered file, not the shared name: this is what a reviewer should open, so that
        # a re-place is always a path they have not seen before.
        # The numbered file, so a reviewer is handed a path nothing has cached.
        "placement_path": str(placement_path),
        "current_path": str(current_path),
    }


def unaccept_result(root: str | Path, level_id: str) -> dict[str, Any]:
    """Reopen an accepted level so it can be generated again.

    Acceptance is not just a flag: it publishes the level's pixels into its neighbours'
    padding. So undoing it has to clear the accepted state first and then rebuild the
    neighbours, which recompute their input from whichever levels are accepted at that
    moment -- with this one no longer among them, its contribution simply is not there.

    The attempts and job snapshots are left alone. They are the record of what was tried;
    only the claim that one of them is final goes away.
    """
    from .package_refresher import refresh_level, refresh_neighbors

    root_path = Path(root).resolve()
    run = read_json(root_path / "run.json")
    level_id = level_id.zfill(2)
    if level_id not in run["levels"]:
        raise KeyError(f"unknown level: {level_id}")
    if run["levels"][level_id].get("state") != LevelState.ACCEPTED.value:
        raise ValueError(
            f"level {level_id} is {run['levels'][level_id].get('state')!r}, not accepted"
        )

    paths = level_paths(root_path, level_id)
    manifest = read_json(paths["manifest"])
    attempt = manifest.get("accepted_attempt")
    accepted_path = paths["root"] / "accepted" / "image.png"
    if accepted_path.exists():
        accepted_path.unlink()

    dropped = ("accepted_image", "accepted_hash", "accepted_attempt", "acceptance_index")
    for key in dropped:
        manifest.pop(key, None)
        run["levels"][level_id].pop(key, None)
    manifest.update({"state": LevelState.GENERATED.value, "updated_at": utc_now()})
    run["levels"][level_id].update(
        {"state": LevelState.GENERATED.value, "updated_at": utc_now()}
    )
    atomic_write_json(paths["manifest"], manifest)
    atomic_write_json(root_path / "run.json", run)

    if attempt is not None:
        job_path = paths["root"] / "jobs" / f"attempt_{int(attempt):03d}" / "job.json"
        if job_path.is_file():
            job = read_json(job_path)
            job["state"] = LevelState.GENERATED.value
            atomic_write_json(job_path, job)

    append_event(root_path, "result_unaccepted", level_id=level_id, attempt=attempt)
    # Its own input first (this puts it back to READY so a new job can be created), then the
    # neighbours, which now rebuild without its pixels in their padding.
    refresh_level(root_path, level_id, force=True)
    refreshed = refresh_neighbors(root_path, level_id)
    return {
        "level_id": level_id,
        "state": read_json(root_path / "run.json")["levels"][level_id]["state"],
        "was_attempt": attempt,
        "refreshed_neighbors": refreshed,
    }


def accept_result(
    root: str | Path,
    level_id: str,
    *,
    attempt: int | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    run = read_json(root_path / "run.json")
    level_id = level_id.zfill(2)
    paths = level_paths(root_path, level_id)
    manifest = read_json(paths["manifest"])
    job_path, job = _job_for_attempt(paths, attempt)
    if job.get("state") != LevelState.GENERATED.value:
        raise ValueError(f"job must be generated before acceptance, got {job.get('state')!r}")
    candidate = Path(job["current_path"])
    accepted_path = paths["root"] / "accepted" / "image.png"
    accepted_path.parent.mkdir(parents=True, exist_ok=True)
    if accepted_path.exists() and not job.get("refine"):
        accepted_hash = sha256_file(accepted_path)
        candidate_hash = sha256_file(candidate)
        if accepted_hash != candidate_hash:
            raise ValueError("accepted image already exists with different content")
    else:
        # A refine attempt is a deliberate second pass over finished art, so it replaces
        # what is there rather than colliding with it.
        shutil.copy2(candidate, accepted_path)

    run["acceptance_counter"] = int(run.get("acceptance_counter", 0)) + 1
    acceptance_index = run["acceptance_counter"]
    job.update({"state": LevelState.ACCEPTED.value, "accepted_at": utc_now()})
    atomic_write_json(job_path, job)
    manifest.update(
        {
            "state": LevelState.ACCEPTED.value,
            "accepted_image": str(accepted_path),
            "accepted_hash": sha256_file(accepted_path),
            "accepted_attempt": int(job["attempt"]),
            "acceptance_index": acceptance_index,
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(paths["manifest"], manifest)
    run["levels"][level_id].update(
        {
            "state": LevelState.ACCEPTED.value,
            "accepted_image": str(accepted_path),
            "accepted_hash": manifest["accepted_hash"],
            "accepted_attempt": int(job["attempt"]),
            "acceptance_index": acceptance_index,
            "updated_at": utc_now(),
        }
    )
    atomic_write_json(root_path / "run.json", run)
    append_event(
        root_path,
        "result_accepted",
        level_id=level_id,
        attempt=int(job["attempt"]),
        acceptance_index=acceptance_index,
    )

    from .package_refresher import refresh_neighbors

    refreshed = refresh_neighbors(root_path, level_id)
    return {
        "level_id": level_id,
        "attempt": int(job["attempt"]),
        "state": LevelState.ACCEPTED.value,
        "accepted_image": str(accepted_path),
        "refreshed_neighbors": refreshed,
    }
