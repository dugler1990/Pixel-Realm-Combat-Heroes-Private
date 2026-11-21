"""The level review page: review_run's loop in the browser, plus dragging the padding into line.

Every action runs the same orchestrate commands as the console loop (review_run), with the
same arguments, so the two agree. Use one of them at a time on a run: both write run.json and
job.json. Commands run in a background thread of this process, one at a time; while one runs
the page only asks for progress. Listens on 127.0.0.1 only. Re-place and accept run inside
this process (``_call_here``), so a pipeline code change needs the page restarted; generate
runs as its own process.

Each level is pinned to one attempt. Re-place, the images and accept all use that attempt's
own files, never merely the newest job on disk.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from PIL import Image

from .assemble import assemble_world
from .checks import format_report, run_checks
from .pod_upscale import (
    PodError,
    SystemRemote,
    parse_ssh_line,
    prepare_pod,
    run_hypir,
)
from .register_level import ensure_name, find_existing, taken_slots
from .job_builder import canvas_asset
from .review_run import (
    CommandFailed,
    _call,
    _candidate,
    _entry,
    _payload,
    attempt_of,
    parse_retry,
    reingest_args,
)
from .state_store import read_json

Image.MAX_IMAGE_PIXELS = None

WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC = {
    "review.html": "text/html; charset=utf-8",
    "leaflet/leaflet.js": "text/javascript; charset=utf-8",
    "leaflet/leaflet.css": "text/css; charset=utf-8",
}
# Where `python -m tools...` resolves from.
REPO = Path(__file__).resolve().parents[3]
IMAGE_KINDS = ("raw", "padding", "result", "overlay")
FIT_IMAGES = ("outline", "holes")  # drawn from the masks, not files: no version of their own
# LevelSelection.grid_rows / grid_columns. A card exists only inside this grid.
MENU_ROWS, MENU_COLS = 3, 4
_SLUG = re.compile(r"^[A-Za-z0-9_]+$")


def _parse_offset(text: str | None) -> tuple[int, int]:
    """``"dx,dy"`` (missing: 0, 0)."""
    if not text:
        return (0, 0)
    parts = [int(v) for v in str(text).split(",")]
    if len(parts) != 2:
        raise ValueError("the offset is dx,dy")
    return parts[0], parts[1]


class _PodSession:
    """The Connect line for this page process. Not written to disk."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.remote: Any = None
        self.host = ""
        self.phase = "idle"
        self.detail = "Paste the RunPod SSH line and press Connect."

    def mark(self, phase: str, detail: str) -> None:
        with self._lock:
            self.phase = phase
            self.detail = detail

    def ready(self, host: str, remote: Any, detail: str) -> None:
        with self._lock:
            self.remote = remote
            self.host = host
            self.phase = "ready"
            self.detail = detail

    def clear(self) -> None:
        with self._lock:
            self.remote = None
            self.host = ""
            self.phase = "idle"
            self.detail = "Disconnected. The pod is still running until you stop it in RunPod."

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"phase": self.phase, "detail": self.detail, "host": self.host,
                    "connected": self.remote is not None}


class RunProgress:
    """What the background command is doing; read by the page without waiting for it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {"running": False}

    def start(self, level_id: str, label: str) -> None:
        with self._lock:
            self._data = {"running": True, "level": level_id, "label": label,
                          "error": None, "message": None}

    def update(self, **values: Any) -> None:
        with self._lock:
            self._data.update(values)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._data.get("running"))


def _call_here(*args: str, fatal: bool = False, cwd: str | Path | None = None,
               main: Callable[[list[str]], None] | None = None) -> dict:
    """Run an orchestrate subcommand inside this process; same answer as ``_call``.

    A fresh Python per press has to load numpy / scipy / cv2 again, which took up to 80 s when
    Windows had them off disk (2026-11-14, level 06). Here they are loaded once. The price:
    a code change to the pipeline needs the page restarted. A refusal (any exception, or a
    non-zero exit) becomes CommandFailed with its message, as ``_call`` does with fatal=False.
    """
    if main is None:
        from .orchestrate import main
    printed = io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):
            main(list(args))
    except SystemExit as stop:
        if stop.code not in (None, 0):
            raise CommandFailed(stop.code if isinstance(stop.code, str) else f"{args[0]} failed")
    except Exception as exc:
        traceback.print_exc()
        raise CommandFailed(f"{type(exc).__name__}: {exc}") from exc
    return _payload(printed.getvalue())


def _publish_playable(png: Path, slug: str, title: str, slot: tuple[int, int] | None) -> dict:
    """Build the playable TMX from the stitched image and put it on the selection grid.

    Same path as ``orchestrate assemble --level-dir``. Tile size 150, so the ground draws at
    the size it was stitched. A level that already has a slot keeps it when ``slot`` is None.
    """
    from argparse import Namespace

    from .orchestrate import _build_and_register

    args = Namespace(
        tile_size=150,
        width_tiles=None,
        height_tiles=None,
        level_dir=str(REPO / "levels" / "Frostreach" / slug),
        template_dir=str(REPO / "levels" / "Frostreach" / "ice_wall_gate"),
        no_register=False,
        level_number=None,
        slot=None if slot is None else f"{slot[0]},{slot[1]}",
    )
    with Image.open(png) as opened:
        size = opened.size
    result = _build_and_register(args, None, Path(png), size)
    if ensure_name(REPO, int(result["level_number"]), title):
        result.setdefault("changed", []).append(str(Path("Code") / "level_layouts.py"))
    result["card_name"] = title
    return result


def _warm_up() -> None:
    """Load the pipeline in the background at start, so the first press does not wait for it."""
    try:
        from . import orchestrate  # noqa: F401
    except Exception:
        traceback.print_exc()


def _version(path: Path | None) -> int | None:
    return path.stat().st_mtime_ns if path is not None and path.is_file() else None


class ReviewPage:
    """The run, the settings per level, and the one background command, behind one lock."""

    def __init__(
        self,
        root: str | Path,
        levels: list[str],
        *,
        feather: int = 0,
        prompt_file: str | None = None,
        call: Callable[..., dict] | None = None,
        generate_call: Callable[..., dict] | None = None,
        checks: Callable[..., dict] = run_checks,
        assemble: Callable[..., tuple] | None = None,
        publish: Callable[..., dict] | None = None,
        slots: Callable[[Path], set] | None = None,
        existing: Callable[..., Any] | None = None,
        remote_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.levels = list(levels)
        self.default_feather = int(feather)
        self.prompt_file = prompt_file
        # Re-place and accept run in this process (fast). Generate keeps its own process: it
        # runs for minutes against the API and must not hold this one's stdout. A ``call``
        # passed in (tests) is used for everything unless ``generate_call`` is given too.
        self.call = call or _call_here
        self.generate_call = generate_call or call or _call
        self.checks_fn = checks
        # The whole run, not the level on screen. Image only: no TMX, no game tables.
        self.assemble_fn = assemble or assemble_world
        self.publish_fn = publish or _publish_playable
        self.slots_fn = slots or taken_slots
        self.existing_fn = existing or find_existing
        # Builds the SSH remote for a parsed Connect line. Tests pass a fake.
        self.remote_factory = remote_factory or SystemRemote
        self.pod = _PodSession()
        self.lock = threading.Lock()
        self.run = RunProgress()
        self.settings: dict[str, dict[str, Any]] = {}
        self.reports: dict[tuple[str, int], str] = {}
        self._padding_cache: dict[tuple[str, int, int], bytes] = {}
        self._fit_cache: dict[str, Any] = {}

    # -- files ----------------------------------------------------------------------------

    def _level(self, level_id: str) -> str:
        if level_id not in self.levels:
            raise KeyError(level_id)
        return level_id

    def _level_dir(self, level_id: str) -> Path:
        return self.root / "levels" / level_id

    def attempts(self, level_id: str) -> list[int]:
        """Attempts with a generation to place, oldest first."""
        found = (attempt_of(p) for p in (self._level_dir(level_id) / "jobs").glob("attempt_*/generated.png"))
        return sorted(n for n in found if n is not None)

    def _job_dir(self, level_id: str, attempt: int) -> Path:
        return self._level_dir(level_id) / "jobs" / f"attempt_{attempt:03d}"

    def _attempt_dir(self, level_id: str, attempt: int) -> Path:
        return self._level_dir(level_id) / "attempts" / f"attempt_{attempt:03d}"

    def _job(self, level_id: str, attempt: int) -> dict[str, Any]:
        path = self._job_dir(level_id, attempt) / "job.json"
        return read_json(path) if path.is_file() else {}

    def _image_path(self, level_id: str, attempt: int, kind: str) -> Path | None:
        if kind == "raw":
            return self._job_dir(level_id, attempt) / "generated.png"
        if kind == "padding":
            return canvas_asset(self._job_dir(level_id, attempt), "locked_pixels")
        if kind == "result":
            placed = self._job(level_id, attempt).get("placement_path")
            if placed and Path(placed).is_file():
                return Path(placed)
            return self._attempt_dir(level_id, attempt) / "current.png"
        if kind == "overlay":
            return self._attempt_dir(level_id, attempt) / "footprint_overlay.png"
        raise KeyError(kind)

    def padding_png(self, level_id: str, attempt: int) -> bytes:
        """The padding as a PNG, transparent outside the locked mask. Cached per file time."""
        job_dir = self._job_dir(level_id, attempt)
        pixels, mask = canvas_asset(job_dir, "locked_pixels"), canvas_asset(job_dir, "locked_mask")
        key = (str(job_dir), _version(pixels) or 0, _version(mask) or 0)
        if key not in self._padding_cache:
            with Image.open(pixels) as colour, Image.open(mask) as alpha:
                picture = colour.convert("RGBA")
                picture.putalpha(alpha.convert("L"))
            buffer = io.BytesIO()
            picture.save(buffer, format="PNG", compress_level=1)
            self._padding_cache = {key: buffer.getvalue()}  # one level open at a time
        return self._padding_cache[key]

    # -- shape fit (the Align view's outline, holes and best offset) ------------------------

    def _fit(self, level_id: str, attempt: int):
        """The attempt's ShapeFit, kept for the attempt on screen (rebuilt if its files change)."""
        from .shape_fit import ShapeFit

        job_dir = self._job_dir(level_id, attempt)
        raw = self._image_path(level_id, attempt, "raw")
        shape = canvas_asset(job_dir, "generation_mask")
        cell = canvas_asset(job_dir, "pending_mask")
        key = (str(job_dir), _version(raw), _version(shape), _version(cell))
        if self._fit_cache.get("key") != key:
            import numpy as np

            with Image.open(raw) as r, Image.open(shape) as s, Image.open(cell) as c:
                fit = ShapeFit(np.asarray(r.convert("RGB")), np.asarray(s.convert("L")) > 0,
                               np.asarray(c.convert("L")) > 0)
            self._fit_cache = {"key": key, "fit": fit, "outline": None}
        return self._fit_cache

    def fit(self, level_id: str, attempt: int, offset: str | None, best: bool) -> dict[str, Any]:
        """Holes a cut leaves at ``offset`` (and, with ``best``, the offset with the fewest)."""
        level_id = self._level(level_id)
        renderer = self._job(level_id, attempt).get("renderer", "warp")
        if renderer != "warp":
            raise ValueError(f"a padding offset needs the warp renderer; this attempt used {renderer}")
        fit = self._fit(level_id, attempt)["fit"]
        out = {"current": fit.score(_parse_offset(offset))}
        if best:
            out["best"] = fit.best()
        return out

    def _png(self, rgba) -> bytes:
        buffer = io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(buffer, format="PNG", compress_level=1)
        return buffer.getvalue()

    def outline_png(self, level_id: str, attempt: int) -> bytes:
        """The level's shape (what the cut keeps) as a yellow line, transparent elsewhere."""
        import cv2
        import numpy as np

        cache = self._fit(level_id, attempt)
        if cache["outline"] is None:
            shape = cache["fit"].shape.astype(np.uint8)
            edge = cv2.morphologyEx(shape, cv2.MORPH_GRADIENT, np.ones((5, 5), np.uint8)) > 0
            rgba = np.zeros(shape.shape + (4,), dtype=np.uint8)
            rgba[edge] = (255, 220, 0, 255)
            cache["outline"] = self._png(rgba)
        return cache["outline"]

    def holes_png(self, level_id: str, attempt: int, offset: str | None) -> bytes:
        """The holes a cut leaves at ``offset``, in pink, drawn 2 px thicker so they show
        when zoomed out."""
        import cv2
        import numpy as np

        holes = self._fit(level_id, attempt)["fit"].holes(_parse_offset(offset))
        thick = cv2.dilate(holes.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        rgba = np.zeros(holes.shape + (4,), dtype=np.uint8)
        rgba[thick] = (255, 60, 255, 255)
        return self._png(rgba)

    def image(self, level_id: str, kind: str, attempt: int, offset: str | None = None) -> Path | bytes:
        if kind == "padding":
            return self.padding_png(level_id, attempt)
        if kind == "outline":
            return self.outline_png(level_id, attempt)
        if kind == "holes":
            return self.holes_png(level_id, attempt, offset)
        path = self._image_path(level_id, attempt, kind)
        if path is None or not path.is_file():
            raise KeyError(f"no {kind} image for level {level_id} attempt {attempt}")
        return path

    # -- what the page shows ----------------------------------------------------------------

    def level_list(self) -> dict[str, Any]:
        states = read_json(self.root / "run.json").get("levels", {})
        return {
            "levels": [
                {"id": lid, "state": states.get(lid, {}).get("state", "unknown"),
                 "attempts": len(self.attempts(lid))}
                for lid in self.levels
            ]
        }

    def _settings(self, level_id: str, attempt: int) -> dict[str, Any]:
        """The toggles for the attempt on screen: as last placed here, else as its job records."""
        saved = self.settings.get(level_id)
        if saved and saved["attempt"] == attempt:
            return saved
        job = self._job(level_id, attempt)
        placed = "placement_path" in job
        settings = {
            "attempt": attempt,
            "feather": int(job.get("placement_feather", 0)) if placed else self.default_feather,
            "warp": bool(job.get("placement_fit_to_mask", False)),
            "cut": bool(job.get("placement_cut_to_mask", False)),
            "align": bool(job.get("placement_align_colours", False)),
            "padding": job.get("placement_padding", "all") != "none",
            "offset": [int(v) for v in job.get("placement_padding_offset", [0, 0])],
            # Only an explicitly recorded method carries over. A placement aligned before the
            # methods existed was the swap, but carrying that over made the next Align colours
            # silently repeat the old method.
            "colour_method": (job.get("placement_colour_alignment") or {}).get("method", "match"),
        }
        self.settings[level_id] = settings
        return settings

    def level_info(self, level_id: str, attempt: Any = None) -> dict[str, Any]:
        level_id = self._level(level_id)
        state = read_json(self.root / "run.json").get("levels", {}).get(level_id, {}).get("state")
        attempts = self.attempts(level_id)
        info: dict[str, Any] = {"id": level_id, "state": state, "attempts": attempts,
                                "attempt": None, "report": None}
        if not attempts:
            return info
        if attempt not in (None, ""):
            attempt = int(attempt)
            if attempt not in attempts:
                raise KeyError(f"level {level_id} has no attempt {attempt}")
        else:
            saved = self.settings.get(level_id)
            attempt = saved["attempt"] if saved and saved["attempt"] in attempts else attempts[-1]
        job = self._job(level_id, attempt)
        width, height = (int(v) for v in job.get("canvas_size", (0, 0)))
        raw = self._image_path(level_id, attempt, "raw")
        if raw.is_file():
            with Image.open(raw) as opened:
                raw_size = list(opened.size)
        else:
            raw_size = [width, height]
        mask = canvas_asset(self._job_dir(level_id, attempt), "locked_mask")
        has_padding = False
        if mask.is_file():
            with Image.open(mask) as opened:
                has_padding = opened.convert("L").getbbox() is not None
        info.update({
            "attempt": attempt,
            "renderer": job.get("renderer", "warp"),
            "job_state": job.get("state"),
            "width": width,
            "height": height,
            "raw_size": raw_size,
            "has_padding": has_padding,
            "settings": self._settings(level_id, attempt),
            "colour_alignment": job.get("placement_colour_alignment"),
            "placement": Path(job["placement_path"]).name if job.get("placement_path") else None,
            "images": {kind: _version(self._image_path(level_id, attempt, kind))
                       for kind in IMAGE_KINDS},
            "report": self.reports.get((level_id, attempt)),
        })
        return info

    # -- commands, each run in the background -------------------------------------------------

    def _start(self, level_id: str, label: str, work: Callable[[], str]) -> dict[str, Any]:
        if self.run.running:
            raise ValueError("A command is already running.")
        self.run.start(level_id, label)
        threading.Thread(target=self._work, args=(work,), daemon=True).start()
        return self.run.snapshot()

    def _work(self, work: Callable[[], str]) -> None:
        with self.lock:
            try:
                self.run.update(message=work())
            except CommandFailed as refused:
                self.run.update(error=f"REFUSED: {refused}")
            except PodError as refused:
                self.run.update(error=str(refused))
            except Exception as exc:
                traceback.print_exc()
                self.run.update(error=f"{type(exc).__name__}: {exc}")
            finally:
                self.run.update(running=False)

    def place(self, level_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Re-place the pinned attempt's generation with these settings. No API call."""
        level_id = self._level(level_id)
        attempt = int(body["attempt"])
        if attempt not in self.attempts(level_id):
            raise KeyError(f"level {level_id} has no attempt {attempt}")
        offset = [int(v) for v in body.get("offset") or (0, 0)]
        if len(offset) != 2:
            raise ValueError("the offset is [dx, dy]")
        renderer = self._job(level_id, attempt).get("renderer", "warp")
        if any(offset) and renderer != "warp":
            raise ValueError(f"a padding offset needs the warp renderer; this attempt used {renderer}")
        settings = {
            "attempt": attempt,
            "feather": max(0, int(body.get("feather", 0))),
            "warp": bool(body.get("warp")),
            "cut": bool(body.get("cut")),
            "align": bool(body.get("align")),
            "padding": bool(body.get("padding", True)),
            "offset": offset,
            "colour_method": body.get("colour_method", "match"),
        }
        if settings["colour_method"] not in ("match", "swap"):
            raise ValueError("the colour method is 'match' or 'swap'")
        args = reingest_args(
            self.root, level_id,
            image=self._image_path(level_id, attempt, "raw"), attempt=attempt,
            feather=settings["feather"], fit=settings["warp"], cut=settings["cut"],
            align=settings["align"], padding=settings["padding"], offset=tuple(offset),
            colour_method=settings["colour_method"],
        )

        def work() -> str:
            payload = self.call(*args, fatal=False, cwd=REPO)
            # Only a placement that happened changes what the page says is applied; a refusal
            # leaves the toggles as they were, as the console does.
            self.settings[level_id] = settings
            self.reports.pop((level_id, attempt), None)
            name = Path(payload.get("placement_path") or "").name
            return f"re-placed attempt {attempt}: {name}"

        return self._start(level_id, f"Re-placing level {level_id} attempt {attempt} (no API call)", work)

    def checks(self, level_id: str, body: dict[str, Any]) -> dict[str, Any]:
        level_id = self._level(level_id)
        attempt = int(body["attempt"])

        def work() -> str:
            report = self.checks_fn(self.root, level_id, attempt)
            self.reports[(level_id, attempt)] = format_report(report)
            return f"checks run on attempt {attempt}"

        return self._start(level_id, f"Running the checks on level {level_id}", work)

    def generate(self, level_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """A new generation: costs an API call. With retry, the criticism goes with it."""
        level_id = self._level(level_id)
        args = ["run", str(self.root), "--levels", level_id]
        if self.prompt_file:
            args += ["--prompt-file", self.prompt_file]
        if body.get("retry"):
            if body.get("r1"):
                reason, attached, note = parse_retry(
                    ("r1 " + str(body.get("reason") or "")).strip(), self.root, level_id)
            else:
                reason = str(body.get("reason") or "")
                image = str(body.get("image") or "").strip()
                attached = Path(image) if image else None
                note = str(body.get("note") or "")
                if attached is not None and not attached.is_file():
                    raise ValueError(f"no such image: {attached}")
            args += ["--retry-reason", reason]
            if attached is not None:
                args += ["--retry-image", str(attached), "--retry-note", note]

        def work() -> str:
            payload = self.generate_call(*args, fatal=False, cwd=REPO)
            entry = _entry(payload, level_id)
            if entry.get("skipped"):
                raise ValueError(f"level {level_id} is already {entry['skipped']}, nothing generated")
            image = _candidate(self.root, level_id, entry)
            if image is None:
                reason = entry.get("error") or entry.get("state") or "no image was produced"
                raise ValueError(f"GENERATION FAILED: {reason}")
            attempt = attempt_of(image) or entry.get("attempt")
            self.settings.pop(level_id, None)
            if attempt is not None:
                self._settings(level_id, int(attempt))
            return f"generated attempt {attempt}"

        label = f"Generating level {level_id} (API call, can take minutes)"
        return self._start(level_id, label, work)

    def accept(self, level_id: str, body: dict[str, Any]) -> dict[str, Any]:
        level_id = self._level(level_id)
        attempt = int(body["attempt"])
        args = ["accept", str(self.root), "--level", level_id, "--attempt", str(attempt)]

        def work() -> str:
            self.call(*args, fatal=False, cwd=REPO)
            return f"accepted level {level_id} attempt {attempt}"

        return self._start(level_id, f"Accepting level {level_id}", work)

    def assemble_map(self) -> dict[str, Any]:
        """Stitch every accepted level in the run into one PNG. No API call, no TMX."""
        out = self.root / "assembled_world.png"

        def work() -> str:
            world, info = self.assemble_fn(self.root, fallback=True)
            out.parent.mkdir(parents=True, exist_ok=True)
            world.save(out)
            placed = info.get("levels_placed", 0)
            total = info.get("levels_total", placed)
            text = f"stitched {placed}/{total} accepted levels to {out}"
            missing = info.get("missing") or []
            if missing:
                text += f"; not accepted, filled from the source map: {', '.join(missing)}"
            return text

        return self._start("map", "Stitching the accepted levels into one map (no API call)", work)

    def _default_slug(self) -> str:
        name = self.root.name
        return name if name.endswith("_play") else f"{name}_play"

    def _default_title(self) -> str:
        stem = re.sub(r"_play$", "", self.root.name)
        stem = re.sub(r"_7x6$", "", stem)
        return " ".join(part.capitalize() for part in stem.split("_") if part)

    def menu_info(self, slug: str | None = None) -> dict[str, Any]:
        """Open cells on the 3 by 4 selection grid, and this folder's card if it has one."""
        slug = slug or self._default_slug()
        if not _SLUG.fullmatch(slug):
            raise ValueError("the folder name is letters, digits and underscores")
        taken = self.slots_fn(REPO)
        found = self.existing_fn(REPO, slug)
        current = None
        if found and found[1]:
            current = {"number": found[0], "slot": [found[1][0], found[1][1]]}
        return {
            "slug": slug,
            "name": self._default_title(),
            "open": [[r, c] for r in range(MENU_ROWS) for c in range(MENU_COLS) if (r, c) not in taken],
            "current": current,
            "rows": MENU_ROWS,
            "columns": MENU_COLS,
            "repo": REPO.name,
        }

    def add_to_menu(self, body: dict[str, Any]) -> dict[str, Any]:
        """Stitch if needed, build the playable map, and put it on the chosen open slot."""
        slug = str(body.get("slug") or self._default_slug())
        info = self.menu_info(slug)
        title = str(body.get("name") or info["name"]).strip()
        if not title or '"' in title or "\n" in title:
            raise ValueError("the card name needs text and no quotes")
        current = info["current"]
        slot: tuple[int, int] | None
        if current:
            slot = None
        else:
            raw = body.get("slot")
            if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                raise ValueError("pick an open slot")
            slot = (int(raw[0]), int(raw[1]))
            if [slot[0], slot[1]] not in info["open"]:
                raise ValueError("that slot is not open")

        def work() -> str:
            png = self.root / "assembled_world.png"
            stitched = ""
            if not png.is_file():
                world, assembled = self.assemble_fn(self.root, fallback=True)
                png.parent.mkdir(parents=True, exist_ok=True)
                world.save(png)
                missing = assembled.get("missing") or []
                stitched = (
                    f" Stitched {assembled.get('levels_placed', 0)}/"
                    f"{assembled.get('levels_total', 0)} first."
                )
                if missing:
                    stitched += f" Not accepted, filled from the source map: {', '.join(missing)}."
            result = self.publish_fn(png, slug, title, slot)
            row, col = result["slot"]
            where = f"row {int(row) + 1}, column {int(col) + 1}"
            verb = "updated" if current else "added"
            return (
                f"{verb} level {result['level_number']} ({title}) at {where} "
                f"in {REPO.name}.{stitched}"
            )

        label = f"Updating {slug} on the level menu" if current else f"Adding {slug} to the level menu"
        return self._start("map", label, work)


    def _upscale_source(self, level_id: str) -> Path | None:
        """Accepted art when the level has it, else the latest generation. None if neither."""
        accepted = self._level_dir(level_id) / "accepted" / "image.png"
        if accepted.is_file():
            return accepted
        attempts = self.attempts(level_id)
        if not attempts:
            return None
        raw = self._image_path(level_id, attempts[-1], "raw")
        return raw if raw is not None and raw.is_file() else None

    def _upscale_files(self, level_id: str) -> dict[str, int | None]:
        folder = self._level_dir(level_id) / "upscale"
        source = self._upscale_source(level_id)
        return {
            "source": _version(source),
            "hypir": _version(folder / "hypir.png"),
            "native": _version(folder / "hypir_native.png"),
        }

    def upscale_status(self, level_id: str | None) -> dict[str, Any]:
        """Read without the page lock: install holds that lock for a long time."""
        status = self.pod.snapshot()
        run = self.run.snapshot()
        status["running"] = bool(run.get("running"))
        status["label"] = run.get("label")
        if level_id and level_id in self.levels:
            status["level"] = level_id
            status["files"] = self._upscale_files(level_id)
        return status

    def upscale_image(self, level_id: str, which: str) -> Path:
        level_id = self._level(level_id)
        if which == "source":
            path = self._upscale_source(level_id)
        elif which == "hypir":
            path = self._level_dir(level_id) / "upscale" / "hypir.png"
        elif which == "native":
            path = self._level_dir(level_id) / "upscale" / "hypir_native.png"
        else:
            raise ValueError("the upscale image is source, hypir, or native")
        if path is None or not path.is_file():
            raise KeyError(f"no {which} image for level {level_id}")
        return path

    def connect_pod(self, body: dict[str, Any]) -> dict[str, Any]:
        target = parse_ssh_line(str(body.get("ssh") or ""))
        if not target.key.is_file():
            raise ValueError(f"SSH key not found: {target.key}")
        host = f"{target.user}@{target.host}:{target.port}"
        self.pod.mark("installing", f"Connecting to {host}")

        def work() -> str:
            try:
                remote = self.remote_factory(target)
                detail = prepare_pod(remote, label=lambda text: self.run.update(label=text))
            except Exception:
                self.pod.mark("idle", "Connect failed. The pod was left as it was.")
                raise
            self.pod.ready(host, remote, detail)
            return detail

        return self._start("upscale", f"Connecting to {host}", work)

    def disconnect_pod(self) -> dict[str, Any]:
        if self.run.running:
            raise ValueError("A command is already running.")
        self.pod.clear()
        return self.pod.snapshot()

    def run_upscale(self, body: dict[str, Any]) -> dict[str, Any]:
        level_id = self._level(str(body.get("level") or ""))
        remote = self.pod.snapshot()
        if not remote["connected"]:
            raise ValueError("Connect to the pod first.")
        source = self._upscale_source(level_id)
        if source is None:
            raise ValueError(f"level {level_id} has no image to send")

        def work() -> str:
            dest = self._level_dir(level_id) / "upscale"
            run_hypir(self.pod.remote, source, dest, label=lambda text: self.run.update(label=text))
            return f"HYPIR wrote levels/{level_id}/upscale/hypir.png from {source.parent.name}/{source.name}."

        return self._start(level_id, f"Running HYPIR on level {level_id}", work)


def dispatch(
    page: ReviewPage, method: str, parts: list[str], query: dict[str, list[str]], body: dict
) -> dict[str, Any] | Path | bytes:
    if method == "GET" and parts == ["levels"]:
        return page.level_list()
    if method == "POST" and parts == ["assemble"]:
        return page.assemble_map()
    if parts[:1] == ["upscale"]:
        action = parts[1] if len(parts) > 1 else ""
        if method == "GET" and action == "image":
            return page.upscale_image((query.get("level") or [""])[0], (query.get("which") or [""])[0])
        if method == "POST" and action == "connect":
            return page.connect_pod(body)
        if method == "POST" and action == "disconnect":
            return page.disconnect_pod()
        if method == "POST" and action == "run":
            return page.run_upscale(body)
    if parts == ["menu"]:
        slug = (query.get("slug") or [None])[0]
        if method == "GET":
            return page.menu_info(slug or None)
        if method == "POST":
            return page.add_to_menu(body)
    if len(parts) >= 2 and parts[0] == "level":
        level_id = page._level(parts[1])
        action = parts[2] if len(parts) > 2 else ""
        attempt = (query.get("attempt") or [None])[0]
        if method == "GET":
            if action == "":
                return page.level_info(level_id, attempt)
            if action == "image" and len(parts) == 4 and parts[3] in IMAGE_KINDS + FIT_IMAGES:
                if attempt in (None, ""):
                    raise ValueError("an image needs ?attempt=")
                return page.image(level_id, parts[3], int(attempt),
                                  (query.get("offset") or [None])[0])
            if action == "fit":
                if attempt in (None, ""):
                    raise ValueError("the fit needs ?attempt=")
                return page.fit(level_id, int(attempt), (query.get("offset") or [None])[0],
                                (query.get("best") or [""])[0] == "1")
        if method == "POST":
            if action == "place":
                return page.place(level_id, body)
            if action == "checks":
                return page.checks(level_id, body)
            if action == "generate":
                return page.generate(level_id, body)
            if action == "accept":
                return page.accept(level_id, body)
    raise KeyError("/".join(parts))


def make_handler(page: ReviewPage) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str, cache: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # Images are asked for with ?v=<file time>, so a cached copy is never stale; the
            # raw generation is ~8 MB and is shown again on every view switch.
            self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, status: int = HTTPStatus.OK) -> None:
            self._send(status, json.dumps(data).encode("utf-8"), "application/json")

        def _handle(self, method: str) -> None:
            url = urlparse(self.path)
            parts = [part for part in url.path.split("/") if part]
            name = "/".join(parts or ["review.html"])
            if method == "GET" and name in STATIC:
                self._send(HTTPStatus.OK, (WEB_DIR / name).read_bytes(), STATIC[name])
                return
            if parts[:1] != ["api"]:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            if parts[1:] == ["progress"]:
                self._json(page.run.snapshot())
                return
            # Install holds the page lock, so this is read the same way as progress.
            if method == "GET" and parts[1:] == ["upscale", "status"]:
                level = (parse_qs(url.query).get("level") or [None])[0]
                self._json(page.upscale_status(level))
                return
            if page.run.running:
                self._json({"error": "A command is running."}, HTTPStatus.CONFLICT)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if method == "POST" else {}
                with page.lock:
                    result = dispatch(page, method, parts[1:], parse_qs(url.query), body)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except KeyError as exc:
                self._json({"error": f"not found: {exc}"}, HTTPStatus.NOT_FOUND)
                return
            except Exception as exc:  # shown in the page and printed here
                traceback.print_exc()
                self._json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if isinstance(result, Path):
                self._send(HTTPStatus.OK, result.read_bytes(), "image/png", cache=True)
            elif isinstance(result, bytes):
                self._send(HTTPStatus.OK, result, "image/png", cache=True)
            else:
                self._json(result)

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

    return Handler


class _OwnPortServer(ThreadingHTTPServer):
    # The default lets a second server bind a port already in use on Windows; the browser's
    # requests are then split between the two.
    allow_reuse_address = False


def serve(page: ReviewPage, port: int, open_browser: bool = True) -> None:
    try:
        server = _OwnPortServer(("127.0.0.1", port), make_handler(page))
    except OSError:
        raise SystemExit(f"Port {port} is already in use by another program: start with --port and another number.")
    url = f"http://127.0.0.1:{port}/"
    threading.Thread(target=_warm_up, daemon=True).start()
    print(f"Level review page: {url}   (Ctrl+C here to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
