"""Tests for the automatic attempt checks."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from tools.painted_map_pipeline.world_levels.checks import (
    footprint,
    full_bleed,
    padding_seam,
)
from tools.painted_map_pipeline.world_levels.job_builder import _with_retry_context
from tools.painted_map_pipeline.world_levels.renderers.base import (
    INPUT,
    SILHOUETTE,
    Request,
)

SIZE = (240, 160)
JOIN_X = 100


def _masks() -> tuple[Image.Image, Image.Image]:
    """Padding on the left of the join, new work on the right."""
    locked = Image.new("L", SIZE, 0)
    pending = Image.new("L", SIZE, 0)
    ImageDraw.Draw(locked).rectangle((0, 0, JOIN_X - 1, SIZE[1]), fill=255)
    ImageDraw.Draw(pending).rectangle((JOIN_X, 0, SIZE[0], SIZE[1]), fill=255)
    return locked, pending


def _noise(seed: int = 3, offset: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    base = rng.integers(90, 150, size=(SIZE[1], SIZE[0], 3), dtype=np.int16)
    return np.clip(base + offset, 0, 255).astype(np.uint8)


def test_padding_seam_passes_when_the_texture_runs_through():
    locked, pending = _masks()
    image = Image.fromarray(_noise(), mode="RGB").convert("RGBA")
    result = padding_seam(image, locked, pending)
    assert result["passed"], result


def test_padding_seam_fails_on_a_colour_step_across_the_join():
    locked, pending = _masks()
    pixels = _noise()
    pixels[:, JOIN_X:] = np.clip(pixels[:, JOIN_X:].astype(np.int16) + 60, 0, 255).astype(np.uint8)
    result = padding_seam(Image.fromarray(pixels, mode="RGB").convert("RGBA"), locked, pending)
    assert not result["passed"]
    assert result["colour_step"] > result["colour_step_limit"]


def test_padding_seam_fails_on_an_edge_ridge_along_the_join():
    """Flat either side, one hard line down the middle: no colour step, pure edge energy."""
    locked, pending = _masks()
    pixels = np.full((SIZE[1], SIZE[0], 3), 120, dtype=np.uint8)
    pixels[:, JOIN_X - 1 : JOIN_X + 1] = 20
    result = padding_seam(Image.fromarray(pixels, mode="RGB").convert("RGBA"), locked, pending)
    assert not result["passed"]
    assert result["edge_ratio"] > result["edge_ratio_limit"]


def test_padding_seam_is_skipped_without_padding():
    _, pending = _masks()
    image = Image.fromarray(_noise(), mode="RGB").convert("RGBA")
    result = padding_seam(image, Image.new("L", SIZE, 0), pending)
    assert result["passed"] and result["skipped"]


def test_footprint_and_full_bleed_catch_their_own_failures():
    mask = Image.new("L", SIZE, 0)
    ImageDraw.Draw(mask).rectangle((0, 0, JOIN_X, SIZE[1]), fill=255)
    painted = Image.new("RGBA", SIZE, (200, 180, 140, 255))
    assert not full_bleed(painted)["passed"]
    assert not footprint(painted, mask, minimum=0.9)["passed"]


def test_retry_context_is_a_no_op_without_previous_attempts(tmp_path):
    """A first attempt has nothing to send back, so the request must be untouched."""
    (tmp_path / "levels" / "01" / "attempts").mkdir(parents=True)
    blank = Image.new("RGBA", (8, 8))
    request = Request(
        images=((INPUT, blank), (SILHOUETTE, blank)),
        prompt="BODY\n",
        size=SIZE,
    )
    assert _with_retry_context(tmp_path, "01", request, "looks wrong") is request


def _run_root(tmp_path, attempts: list[str]):
    """A minimal level directory: one raw image per attempt, newest last."""
    level = tmp_path / "levels" / "01"
    for index, _ in enumerate(attempts, start=1):
        directory = level / "attempts" / f"attempt_{index:03d}"
        directory.mkdir(parents=True)
        Image.new("RGBA", (16, 16), (120, 100, 80, 255)).save(directory / "generated.raw.png")
    return tmp_path


def _request():
    blank = Image.new("RGBA", (8, 8))
    return Request(images=((INPUT, blank), (SILHOUETTE, blank)), prompt="BODY\n", size=SIZE)


def test_retry_history_accumulates_across_attempts(tmp_path):
    """Reason two must still carry reason one, so a fixed mistake is not remade."""
    root = _run_root(tmp_path, ["one"])
    first = _with_retry_context(root, "01", _request(), "you painted past the shape")
    assert [c.role for c, _ in first.images] == ["terrain", "silhouette", "retry"]
    assert "you painted past the shape" in first.prompt

    # a second attempt lands, and is rejected for a different reason
    second_dir = root / "levels" / "01" / "attempts" / "attempt_002"
    second_dir.mkdir(parents=True)
    Image.new("RGBA", (16, 16)).save(second_dir / "generated.raw.png")
    second = _with_retry_context(root, "01", _request(), "now the join has a hard line")

    assert [c.role for c, _ in second.images] == ["terrain", "silhouette", "retry", "retry"]
    assert "you painted past the shape" in second.prompt
    assert "now the join has a hard line" in second.prompt
    assert "Image 3 is your first attempt" in second.prompt
    assert "Image 4 is your second attempt" in second.prompt


def test_retry_history_is_capped(tmp_path):
    from tools.painted_map_pipeline.world_levels.job_builder import RETRY_HISTORY

    root = _run_root(tmp_path, [str(index) for index in range(RETRY_HISTORY + 3)])
    for index in range(1, RETRY_HISTORY + 3):
        directory = root / "levels" / "01" / "attempts" / f"attempt_{index:03d}"
        (directory / "rejection.txt").write_text(f"reason {index}\n", encoding="utf-8")
    request = _with_retry_context(root, "01", _request(), "the newest reason")
    retries = [c for c, _ in request.images if c.role == "retry"]
    assert len(retries) == RETRY_HISTORY
    assert "the newest reason" in request.prompt
    assert "reason 1" not in request.prompt


def test_footprint_overlay_marks_missing_and_spilled():
    """The picture must mark exactly the pixels the score counts, or they tell different stories."""
    from tools.painted_map_pipeline.world_levels.checks import (
        OVERLAY_MISSING,
        OVERLAY_SPILLED,
        footprint_overlay,
    )

    mask = Image.new("L", (60, 60), 0)
    ImageDraw.Draw(mask).rectangle((10, 10, 39, 39), fill=255)
    drawn = Image.new("RGB", (60, 60), (0, 0, 0))
    ImageDraw.Draw(drawn).rectangle((20, 20, 49, 49), fill=(200, 150, 100))

    result = footprint(drawn.convert("RGBA"), mask, minimum=0.9)
    assert result["missing_px"] == 30 * 30 - 20 * 20      # asked for, left black
    assert result["spilled_px"] == 30 * 30 - 20 * 20      # painted, should be black

    overlay = np.asarray(footprint_overlay(drawn, mask))
    # a pixel in each category has moved toward its marker colour
    assert overlay[12, 12][0] > 100 and overlay[12, 12][2] > 100     # magenta side
    assert overlay[45, 45][1] > 100 and overlay[45, 45][2] > 100     # cyan side
    assert tuple(overlay[25, 25]) not in {OVERLAY_MISSING, OVERLAY_SPILLED}   # agreed area


def test_attachment_is_one_shot_and_last_in_the_roster(tmp_path):
    """It answers 'look at this, for this retry' -- it must not linger into the next one."""
    root = _run_root(tmp_path, ["one"])
    attached = tmp_path / "evidence.png"
    Image.new("RGBA", (32, 32), (10, 200, 200, 255)).save(attached)

    with_image = _with_retry_context(
        root, "01", _request(), "the edge spilled", (attached, "the error marked in cyan")
    )
    roles = [c.role for c, _ in with_image.images]
    assert roles == ["terrain", "silhouette", "retry", "annotation"]
    assert "Image 4: the error marked in cyan" in with_image.prompt

    # the typed reason persists; the attachment does not
    again = _with_retry_context(root, "01", _request(), "still wrong")
    assert [c.role for c, _ in again.images] == ["terrain", "silhouette", "retry"]
    assert "the error marked in cyan" not in again.prompt


def _overlay_root(tmp_path, monkeypatch, overlay="footprint_overlay.png"):
    """A stub run whose checks report an overlay, so parse_retry has something to resolve."""
    from tools.painted_map_pipeline.world_levels import review_run

    path = tmp_path / overlay
    Image.new("RGBA", (16, 16)).save(path)
    monkeypatch.setattr(review_run, "run_checks", lambda *a, **k: {"overlay_path": str(path)})
    return path


def test_r1_attaches_the_overlay_with_both_the_colours_and_the_directive(tmp_path, monkeypatch):
    from tools.painted_map_pipeline.world_levels.checks import (
        FOOTPRINT_OVERLAY_DIRECTIVE,
        FOOTPRINT_OVERLAY_NOTE,
    )
    from tools.painted_map_pipeline.world_levels.review_run import parse_retry

    path = _overlay_root(tmp_path, monkeypatch)
    reason, attached, note = parse_retry("r1", tmp_path, "01")
    assert attached == path and reason == ""
    # both halves: what the colours mean, then what to do about it
    assert FOOTPRINT_OVERLAY_NOTE in note
    assert FOOTPRINT_OVERLAY_DIRECTIVE in note


def test_r1_appends_anything_typed_after_it(tmp_path, monkeypatch):
    from tools.painted_map_pipeline.world_levels.review_run import parse_retry

    _overlay_root(tmp_path, monkeypatch)
    _, attached, note = parse_retry("r1 the top edge especially", tmp_path, "01")
    assert attached is not None
    assert note.endswith("the top edge especially")


def test_r1_is_not_swallowed_by_the_plain_r_branch(tmp_path, monkeypatch):
    """`r1` starts with `r`, so a naive prefix test would route it to the manual parser."""
    from tools.painted_map_pipeline.world_levels.review_run import parse_retry

    _overlay_root(tmp_path, monkeypatch)
    for line in ("r1", "r1 more words", "R1"):
        _, attached, _ = parse_retry(line, tmp_path, "01")
        assert attached is not None, line
    # and a plain r with no image still returns none
    assert parse_retry("r just words", tmp_path, "01")[1] is None


def test_r1_says_so_when_there_is_no_overlay(tmp_path, monkeypatch):
    from tools.painted_map_pipeline.world_levels import review_run

    monkeypatch.setattr(
        review_run, "run_checks", lambda *a, **k: {"error": "this level has no attempts yet"}
    )
    try:
        review_run.parse_retry("r1", tmp_path, "01")
    except FileNotFoundError as exc:
        assert "no attempts" in str(exc)
    else:
        raise AssertionError("expected a FileNotFoundError")


def _fake_job(tmp_path, canvas, frame, input_size):
    """A job directory with just the pieces write_api_mask reads."""
    import json

    from tools.painted_map_pipeline.world_levels.models import GenerationJob

    (tmp_path / "canvas").mkdir(parents=True, exist_ok=True)
    mask = Image.new("L", canvas, 0)
    ImageDraw.Draw(mask).rectangle((canvas[0] // 4, canvas[1] // 4, canvas[0] // 2, canvas[1] // 2), fill=255)
    mask.save(tmp_path / "canvas" / "generation_mask.png")
    (tmp_path / "job.json").write_text(json.dumps({"frame": frame, "input_size": list(input_size)}))
    return GenerationJob(
        level_id="01", attempt=1, directory=tmp_path,
        input_path=tmp_path / "input.png", prompt_path=tmp_path / "prompt.txt",
        output_path=tmp_path / "generated.png", manifest_path=tmp_path / "job.json",
    )


def test_backend_hands_the_client_a_plain_mask_it_can_convert(tmp_path):
    """The double conversion that broke this: the backend must not pre-convert to RGBA.

    ``ImageClient.generate`` owns the conversion. A mask converted twice comes out with black
    RGB channels, which the client reads as nothing to edit.
    """
    from tools.painted_map_pipeline.image_client import OpenAIImageClient
    from tools.painted_map_pipeline.world_levels.generation_backend import write_generation_mask

    job = _fake_job(tmp_path, (80, 60), {"origin": [0, 0], "size": [80, 60]}, (80, 60))
    written = Image.open(write_generation_mask(job, (80, 60)))
    assert written.mode == "L", "the client converts; handing it RGBA converts twice"

    converted = Image.open(OpenAIImageClient._alpha_mask(tmp_path / "api_mask.png", (80, 60)))
    editable = np.asarray(converted)[..., 3] == 255
    assert editable.any(), "the client must find an editable area"
    assert np.array_equal(editable, np.asarray(written) > 0)


def test_alpha_mask_makes_the_repaint_area_opaque_not_transparent(tmp_path):
    """The polarity is the reverse of OpenAI's documented one, and it is measured.

    Two identical calls on level 02 differing only in this: alpha 0 over the polygon (what the
    docs describe) painted the whole canvas at IoU 0.305; alpha 255 over it painted the polygon
    at IoU 0.970. Sending the documented polarity asks for everything EXCEPT the level.
    """
    from tools.painted_map_pipeline.image_client import OpenAIImageClient

    plain = tmp_path / "plain.png"
    mask = Image.new("L", (40, 30), 0)
    ImageDraw.Draw(mask).rectangle((5, 5, 20, 20), fill=255)
    mask.save(plain)

    alpha = np.asarray(Image.open(OpenAIImageClient._alpha_mask(plain, (40, 30))))[..., 3]
    assert set(alpha[np.asarray(mask) > 0].tolist()) == {255}   # white -> opaque -> repainted
    assert set(alpha[np.asarray(mask) == 0].tolist()) == {0}    # black -> transparent -> kept


def test_generation_mask_is_cropped_to_the_frame_when_the_request_is_a_crop(tmp_path):
    """A mask whose dimensions do not match the image it accompanies is rejected by the API."""
    from tools.painted_map_pipeline.world_levels.generation_backend import write_generation_mask

    frame = {"origin": [10, 6], "size": [40, 30]}
    job = _fake_job(tmp_path, (80, 60), frame, (40, 30))
    written = Image.open(write_generation_mask(job, (40, 30)))
    assert written.size == (40, 30)

    canvas = np.asarray(Image.open(tmp_path / "canvas" / "generation_mask.png")) > 0
    assert np.array_equal(np.asarray(written) > 0, canvas[6:36, 10:50])


def test_the_prompt_names_image_1_and_no_longer_argues_for_the_outline():
    """Attempt 12 returned the locator: 0.80 IoU against image 3, 0.43 against image 1.

    Every other image said "context only" in its own roster line, but nothing said which one
    was the subject, and the locator was the only picture in the set that looked like a
    finished map. So both branches must still name image 1.

    What they must NOT do any more is argue for the outline. The API mask holds the shape,
    and restating it only competes with the instructions that still have to land.
    """
    from tools.painted_map_pipeline.world_levels.renderers.base import INPUT, LOCATOR, PADDING
    from tools.painted_map_pipeline.world_levels.renderers.warp import build_prompt

    seed = build_prompt("", [INPUT, LOCATOR])
    padded = build_prompt("", [INPUT, PADDING, LOCATOR])

    for text in (seed, padded):
        assert "Only image 1 is drawn" in text
        assert "none of them is the picture to return" in text
        assert "outline" not in text.lower()
        assert "stays pure black" not in text

    # numbering still follows the roster: the padding is image 2 now the silhouette is gone
    assert "image 2 shows that" in padded


def test_cut_to_mask_trims_the_spill_without_moving_anything():
    """The non-deforming sibling of the warp: overshoot dropped, nothing shifted."""
    from tools.painted_map_pipeline.world_levels.land_fit import cut_to_mask

    mask = Image.new("L", (40, 30), 0)
    ImageDraw.Draw(mask).rectangle((10, 5, 25, 20), fill=255)
    # painted wider than the polygon in both directions
    art = Image.new("RGBA", (40, 30), (0, 0, 0, 255))
    ImageDraw.Draw(art).rectangle((6, 2, 30, 24), fill=(200, 120, 40, 255))

    cut = cut_to_mask(art, mask, outside_color=(0, 0, 0, 255))
    kept = np.asarray(cut.convert("RGB")).sum(axis=2) > 0
    inside = np.asarray(mask) > 0
    assert np.array_equal(kept, inside), "everything outside the polygon must be gone"
    # and what survived was not moved
    assert np.array_equal(
        np.asarray(cut.convert("RGB"))[inside], np.asarray(art.convert("RGB"))[inside]
    )


def test_cut_iou_reports_coverage_and_ignores_spill(tmp_path):
    """cut_iou answers "how much of the polygon got painted", which spill cannot change.

    The raw IoU blurs two different failures together. Spill is one composite from perfect;
    a shortfall leaves holes and has to be redrawn. Only the second may move cut_iou.
    """
    from tools.painted_map_pipeline.world_levels.checks import footprint

    mask = Image.new("L", (40, 30), 0)
    ImageDraw.Draw(mask).rectangle((10, 5, 25, 20), fill=255)

    spilled = Image.new("RGB", (40, 30), (0, 0, 0))
    ImageDraw.Draw(spilled).rectangle((6, 2, 30, 24), fill=(200, 120, 40))
    result = footprint(spilled, mask, minimum=0.9)
    assert result["cut_iou"] == 1.0, "pure spill is fully recoverable by cutting"
    assert result["iou"] < 1.0 and result["spilled_px"] > 0

    short = Image.new("RGB", (40, 30), (0, 0, 0))
    ImageDraw.Draw(short).rectangle((10, 5, 25, 14), fill=(200, 120, 40))
    holes = footprint(short, mask, minimum=0.9)
    assert holes["cut_iou"] < 1.0, "a shortfall cannot be cut away"
    assert holes["missing_px"] > 0


def test_newest_attempt_reads_the_disk_not_the_bookkeeping(tmp_path):
    """--continue reopens the last generation, so it must find the real newest one.

    Deliberately not run.json's ``latest_candidate``: that is not cleared when a run fails,
    so it goes on naming an older attempt -- which is how a stale image was once offered for
    accept as though it were fresh.
    """
    from tools.painted_map_pipeline.world_levels.review_run import newest_attempt

    attempts = tmp_path / "levels" / "04" / "attempts"
    assert newest_attempt(tmp_path, "04") is None            # nothing generated yet

    for name in ("attempt_001", "attempt_002", "attempt_010"):
        (attempts / name).mkdir(parents=True)
        (attempts / name / "current.png").write_bytes(b"x")
    # a job directory with no placed image must not win
    (attempts / "attempt_011").mkdir()

    assert newest_attempt(tmp_path, "04") == str(attempts / "attempt_010" / "current.png")


def test_coverage_fails_when_the_generation_is_smaller_than_its_polygon():
    """Shortfall and spill need different answers, and one IoU hides that.

    A level 0.9998 by IoU can still be missing pixels, and those are copied verbatim into
    whichever neighbour inherits that ground -- 28,153 unpainted pixels on one level put an
    11-row black bar into the middle of its neighbour's input. Nothing downstream can fill
    them in, so this has to be visible on its own.
    """
    from tools.painted_map_pipeline.world_levels.checks import coverage, footprint

    mask = Image.new("L", (200, 200), 0)
    ImageDraw.Draw(mask).rectangle((20, 20, 180, 180), fill=255)

    short = Image.new("RGB", (200, 200), (0, 0, 0))
    ImageDraw.Draw(short).rectangle((20, 20, 180, 170), fill=(180, 140, 90))
    result = coverage(short, mask)
    assert not result["passed"] and result["missing_px"] > 0

    # spill alone must not trip it: a cut fixes that, and it is not a reason to regenerate
    spilled = Image.new("RGB", (200, 200), (0, 0, 0))
    ImageDraw.Draw(spilled).rectangle((10, 10, 190, 190), fill=(180, 140, 90))
    assert coverage(spilled, mask)["passed"]
    assert footprint(spilled, mask, minimum=0.9)["missing_px"] == 0

    exact = Image.new("RGB", (200, 200), (0, 0, 0))
    ImageDraw.Draw(exact).rectangle((20, 20, 180, 180), fill=(180, 140, 90))
    assert coverage(exact, mask)["passed"]
