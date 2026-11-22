"""The level studio: pick a region, compose it, scale and grid it, then open the review page.

    python -m tools.painted_map_pipeline.world_levels.studio_page [--port 8766]

One server, four steps. The cell review is the existing review page, served at ``/review``
once a run has been prepared. ``review_page`` is unchanged and does not serve this.

Buttons call the pipeline functions. One command at a time, shared with the review page,
so a compose cannot run during a re-place. Image paths resolve only under
``generated/world_levels/`` and the world-map PNGs directly in ``levels/Frostreach/``.
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import re
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from PIL import Image

from ..bootstrap_from_png import bootstrap_level
from .compose import accept_composition, compose_level
from .config import load_config
from .make_grid_plan import DEFAULT_CROP_MARGIN, DEFAULT_OVERLAP_BUFFER, write_plan
from .package_builder import prepare_run
from .review_web import (
    STATIC,
    WEB_DIR,
    ReviewPage,
    RunProgress,
    _OwnPortServer,
    dispatch,
)
from .snap_landmass import snap_map

Image.MAX_IMAGE_PIXELS = None

REPO = Path(__file__).resolve().parents[3]
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,80}")
_LEVEL = re.compile(r"\d{2}")
_MODEL = "gpt-image-2"
_QUALITIES = {"low", "medium", "high"}
PRESET_TILES = (33, 18, 681)  # the two full levels: 22473 x 12258
PRESET_GRID = (7, 6)
_STYLE = (
    "Richly detailed top-down / slightly 2.5D painted pixel-art RPG ground, finished "
    "game-art quality. Preserve the layout exactly; do not invent or remove structures. "
    "Even lighting, no cast shadows, no text or labels."
)
_JOB_FILES = {
    "plan_overlay.png": ("plan_overlay.png",),
    "snap_overlay.png": ("scale", "snap_overlay.png"),
    "background.png": ("scale", "background.png"),
    "snapped.png": ("scale", "background_snapped.png"),
}


def _safe_name(value: Any) -> str:
    name = str(value or "").strip()
    if not _NAME.fullmatch(name):
        raise ValueError("name must be a folder name, without a path")
    return name


def _level_id(value: Any) -> str:
    text = str(value or "").strip()
    if not _LEVEL.fullmatch(text):
        raise ValueError("level id must be two digits, for example 07")
    return text


def _csv_names(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (row.get("id") or "").zfill(2): row.get("name") or row.get("id") or ""
            for row in csv.DictReader(handle)
            if row.get("id")
        }


class Studio:
    """The runs on disk, the one background command, and the review page once a run is open."""

    def __init__(self, repo: Path | None = None) -> None:
        self.repo = Path(repo or REPO).resolve()
        self.runs_root = self.repo / "generated" / "world_levels"
        self.job = RunProgress()
        self.lock = threading.Lock()
        self.review: ReviewPage | None = None
        self.log: list[str] = []

    # -- files ----------------------------------------------------------------------------

    def _note(self, text: str) -> None:
        for line in str(text).splitlines():
            if line.strip():
                self.log.append(line.rstrip())
        del self.log[:-200]

    def _run_dir(self, name: str) -> Path:
        path = self.runs_root / _safe_name(name)
        if not (path / "run.json").is_file() and not (path / "levels").is_dir():
            raise KeyError(name)
        return path

    def _job_dir(self, name: str) -> Path:
        return self.runs_root / _safe_name(name)

    def _level_dir(self, run: str, level: str) -> Path:
        path = self._run_dir(run) / "levels" / _level_id(level)
        if not path.is_dir():
            raise KeyError(f"{run}/{level}")
        return path

    def _names(self, run_dir: Path) -> dict[str, str]:
        config = {}
        for filename in ("config.json", "config.resolved.json"):
            path = run_dir / filename
            if path.is_file():
                try:
                    config = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    config = {}
                break
        plan = config.get("level_plan")
        found = _csv_names(Path(plan)) if plan else {}
        if not found:
            found = _csv_names(run_dir / "plan.csv")
        if not found:
            found = _csv_names(self.repo / "levels" / "Frostreach" / "proposed_25_level_areas.csv")
        return found

    def _refuse_foreign(self, job: Path) -> None:
        """A generation run that this studio did not start is not a place to write a scale into."""
        levels = job / "levels"
        if (job / "studio.json").is_file() or not levels.is_dir():
            return
        for level in levels.iterdir():
            if (level / "accepted" / "image.png").is_file():
                raise ValueError(
                    f"{job.name} is an existing generation run; choose a new folder name"
                )

    def resolve_image(self, raw: str) -> Path:
        """A PNG under the world-level runs, or a world-map PNG in levels/Frostreach/."""
        text = str(raw or "").strip()
        if not text:
            raise ValueError("image path is empty")
        path = Path(text)
        path = path.resolve() if path.is_absolute() else (self.repo / path).resolve()
        if path.suffix.lower() != ".png" or not path.is_file():
            raise ValueError("image is outside the level studio")
        frost = (self.repo / "levels" / "Frostreach").resolve()
        runs = self.runs_root.resolve()
        if path.parent == frost or path == runs or runs in path.parents:
            return path
        raise ValueError("image is outside the level studio")

    def image_for(self, query: dict[str, list[str]]) -> Path:
        raw = (query.get("path") or [None])[0]
        if raw:
            return self.resolve_image(raw)
        kind = (query.get("kind") or [""])[0]
        if kind in _JOB_FILES:
            parts = _JOB_FILES[kind]
            path = self._job_dir((query.get("job") or [""])[0]).joinpath(*parts)
            return self.resolve_image(str(path))
        level_dir = self._level_dir(
            (query.get("run") or [""])[0], (query.get("level") or [""])[0]
        )
        attempt = (query.get("attempt") or [""])[0]
        if kind == "accepted":
            path = level_dir / "accepted" / "image.png"
        elif kind == "locator":
            path = level_dir / "locator.png"
        elif kind == "locked":
            path = level_dir / "composed" / "composed.png"
        elif kind in {"composed", "player"}:
            folder = level_dir / "composed" / f"attempt_{int(attempt):03d}"
            path = folder / ("composed_with_player.png" if kind == "player" else "composed.png")
        else:
            raise ValueError("unknown image")
        return self.resolve_image(str(path))

    # -- what the page shows ----------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        snap = self.job.snapshot()
        snap["openai_key"] = bool(os.environ.get("OPENAI_API_KEY"))
        snap["log"] = self.log[-40:]
        snap["review"] = str(self.review.root) if self.review else None
        return snap

    def list_worlds(self) -> dict[str, Any]:
        frost = self.repo / "levels" / "Frostreach"
        worlds = [
            {"name": path.name, "path": str(path)}
            for path in sorted(frost.glob("*.png"))
            if path.is_file()
        ]
        return {"worlds": worlds}

    def list_runs(self) -> dict[str, Any]:
        runs = []
        if not self.runs_root.is_dir():
            return {"runs": runs}
        for run_dir in sorted(path for path in self.runs_root.iterdir() if path.is_dir()):
            if not (run_dir / "run.json").is_file() and not (run_dir / "levels").is_dir():
                continue
            names = self._names(run_dir)
            levels = []
            levels_dir = run_dir / "levels"
            if levels_dir.is_dir():
                for level_dir in sorted(path for path in levels_dir.iterdir() if path.is_dir()):
                    if not (level_dir / "accepted" / "image.png").is_file():
                        continue
                    if not _LEVEL.fullmatch(level_dir.name):
                        continue
                    attempts = [
                        int(path.parent.name.split("_")[-1])
                        for path in level_dir.glob("composed/attempt_*/composed.png")
                    ]
                    levels.append({
                        "id": level_dir.name,
                        "name": names.get(level_dir.name) or level_dir.name,
                        "locator": (level_dir / "locator.png").is_file(),
                        "composed": (level_dir / "composed" / "composed.png").is_file(),
                        "attempts": sorted(attempts),
                    })
            if not levels and not (run_dir / "run.json").is_file():
                continue
            config_world = ""
            for filename in ("config.json", "config.resolved.json"):
                path = run_dir / filename
                if path.is_file():
                    try:
                        config_world = str(json.loads(path.read_text(encoding="utf-8")).get("world_map") or "")
                    except json.JSONDecodeError:
                        config_world = ""
                    break
            runs.append({
                "name": run_dir.name,
                "world_map": config_world,
                "prepared": (run_dir / "run.json").is_file(),
                "levels": levels,
            })
        return {"runs": runs}

    def compose_state(self, run: str, level: str) -> dict[str, Any]:
        level_dir = self._level_dir(run, level)
        attempts = []
        for path in sorted(level_dir.glob("composed/attempt_*/composed.png")):
            number = int(path.parent.name.split("_")[-1])
            prompt_file = path.parent / "prompt.txt"
            attempts.append({
                "attempt": number,
                "player": (path.parent / "composed_with_player.png").is_file(),
                "prompt": prompt_file.read_text(encoding="utf-8") if prompt_file.is_file() else "",
            })
        box = level_dir / "composed" / "prompt_box.txt"
        locked = level_dir / "composed" / "composed.png"
        return {
            "run": run,
            "level": level,
            "source": "composed" if locked.is_file() else "accepted",
            "attempts": attempts,
            "accepted_attempt": self._accepted_attempt(level_dir) if locked.is_file() else None,
            "prompt": box.read_text(encoding="utf-8") if box.is_file() else "",
        }

    def _accepted_attempt(self, level_dir: Path) -> int | None:
        locked = level_dir / "composed" / "composed.png"
        if not locked.is_file():
            return None
        target = locked.read_bytes()
        for path in level_dir.glob("composed/attempt_*/composed.png"):
            if path.read_bytes() == target:
                return int(path.parent.name.split("_")[-1])
        return None

    def job_state(self, name: str) -> dict[str, Any]:
        job = self._job_dir(name)
        grid_path = job / "grid.json"
        studio_path = job / "studio.json"
        grid = json.loads(grid_path.read_text(encoding="utf-8")) if grid_path.is_file() else None
        source = json.loads(studio_path.read_text(encoding="utf-8")) if studio_path.is_file() else None
        return {
            "name": name,
            "scaled": (job / "scale" / "background.png").is_file(),
            "snapped": (job / "scale" / "background_snapped.png").is_file(),
            "planned": (job / "plan.csv").is_file(),
            "prepared": (job / "run.json").is_file(),
            "grid": grid,
            "source": source,
        }

    # -- commands -------------------------------------------------------------------------

    def busy(self) -> bool:
        return self.job.running or (self.review is not None and self.review.run.running)

    def start(self, label: str, work: Callable[[], Any]) -> dict[str, Any]:
        with self.lock:
            if self.busy():
                raise ValueError("A command is running.")
            self.job.start("studio", label)

        def wrapped() -> None:
            buffer = io.StringIO()
            try:
                with contextlib.redirect_stdout(buffer):
                    message = work()
                text = buffer.getvalue().strip()
                if text:
                    self._note(text)
                self.job.update(running=False, message=str(message or "done"), error=None)
            except Exception as exc:
                trailed = buffer.getvalue().strip()
                if trailed:
                    self._note(trailed)
                traceback.print_exc()
                self.job.update(running=False, error=f"{type(exc).__name__}: {exc}")

        threading.Thread(target=wrapped, daemon=True).start()
        return self.job.snapshot()

    def source_png(self, run: str, level: str) -> Path:
        """The accepted composition when there is one, otherwise the accepted region art."""
        level_dir = self._level_dir(run, level)
        locked = level_dir / "composed" / "composed.png"
        if locked.is_file():
            return locked
        accepted = level_dir / "accepted" / "image.png"
        if not accepted.is_file():
            raise ValueError(f"level {level} has no accepted image")
        return accepted

    def compose(
        self,
        run: str,
        level: str,
        prompt: str,
        *,
        quality: str = "medium",
        model: str = _MODEL,
        player_px: int | None = 8,
    ) -> dict[str, Any]:
        prompt = str(prompt or "").strip()
        if not prompt:
            raise ValueError("the prompt is empty")
        if not prompt.isascii():
            raise ValueError("the prompt must be plain ASCII")
        quality = str(quality or "medium").lower()
        if quality not in _QUALITIES:
            raise ValueError("quality must be low, medium or high")
        if str(model or _MODEL) != _MODEL:
            raise ValueError("the compose pass uses gpt-image-2")
        if player_px is not None:
            player_px = int(player_px)
            if not 1 <= player_px <= 64:
                raise ValueError("player height must be between 1 and 64")
        level_dir = self._level_dir(run, level)
        root = level_dir.parents[1]
        box = level_dir / "composed"
        box.mkdir(parents=True, exist_ok=True)
        (box / "prompt_box.txt").write_text(prompt + "\n", encoding="utf-8")
        prompt_path = box / "prompt_from_studio.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        sprite = self.repo / "image_assets" / "barbwalk" / "0.png"

        def work() -> str:
            result = compose_level(
                root,
                _level_id(level),
                prompt_path,
                player_px=player_px,
                player_sprite=sprite,
                generation={"model": _MODEL, "quality": quality},
            )
            return f"attempt {result['attempt']}"

        return self.start(f"compose {run} {level}", work)

    def accept(self, run: str, level: str, attempt: int) -> dict[str, Any]:
        root = self._level_dir(run, level).parents[1]
        return accept_composition(root, _level_id(level), int(attempt))

    def scale(
        self,
        run: str,
        level: str,
        name: str,
        *,
        width_tiles: int = PRESET_TILES[0],
        height_tiles: int = PRESET_TILES[1],
        tile_size: int = PRESET_TILES[2],
    ) -> dict[str, Any]:
        width_tiles, height_tiles, tile_size = int(width_tiles), int(height_tiles), int(tile_size)
        if min(width_tiles, height_tiles, tile_size) < 1:
            raise ValueError("tile counts and tile size must be positive")
        if width_tiles * tile_size > 40000 or height_tiles * tile_size > 40000:
            raise ValueError("that scale is larger than the maps this pipeline builds")
        source = self.source_png(run, level)
        job = self._job_dir(name)
        self._refuse_foreign(job)
        template = self.repo / "levels" / "Frostreach" / "ice_wall_gate"

        def work() -> str:
            manifest = bootstrap_level(
                source,
                job / "scale",
                width_tiles=width_tiles,
                height_tiles=height_tiles,
                tile_size=tile_size,
                template_dir=template,
            )
            (job / "studio.json").write_text(json.dumps({
                "source_run": run,
                "source_level": level,
                "source_png": str(source),
                "width_tiles": width_tiles,
                "height_tiles": height_tiles,
                "tile_size": tile_size,
            }, indent=2) + "\n", encoding="utf-8")
            return manifest["background_png"]

        return self.start(f"scale {name}", work)

    def snap(self, name: str) -> dict[str, Any]:
        job = self._job_dir(name)
        background = job / "scale" / "background.png"
        if not background.is_file():
            raise ValueError("scale this level first")

        def work() -> str:
            result = snap_map(
                background,
                job / "scale" / "background_snapped.png",
                polygon_out=job / "scale" / "landmass_polygon.json",
                overlay=job / "scale" / "snap_overlay.png",
            )
            return result["out"]

        return self.start(f"snap {name}", work)

    def write_grid(
        self,
        name: str,
        cols: int,
        rows: int,
        *,
        region: str = "",
        name_prefix: str = "Level",
        overlap_buffer: int = DEFAULT_OVERLAP_BUFFER,
        crop_margin: int = DEFAULT_CROP_MARGIN,
    ) -> dict[str, Any]:
        """Lay the grid over the snapped map. Does not snap and does not prepare."""
        cols, rows = int(cols), int(rows)
        if not 1 <= cols <= 40 or not 1 <= rows <= 40:
            raise ValueError("cols and rows must be between 1 and 40")
        job = self._job_dir(name)
        snapped = job / "scale" / "background_snapped.png"
        polygon_path = job / "scale" / "landmass_polygon.json"
        if not snapped.is_file() or not polygon_path.is_file():
            raise ValueError("snap the scaled map first")
        polygon = json.loads(polygon_path.read_text(encoding="utf-8"))["polygon"]
        info = write_plan(
            snapped,
            polygon,
            job / "plan.csv",
            cols=cols,
            rows=rows,
            overlay=job / "plan_overlay.png",
            region=str(region or ""),
            name_prefix=str(name_prefix or "Level"),
            overlap_buffer=int(overlap_buffer),
            crop_margin=int(crop_margin),
        )
        info.update({"cols": cols, "rows": rows})
        (job / "grid.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
        return info

    def prepare(
        self,
        name: str,
        *,
        quality: str = "medium",
        model: str = _MODEL,
        style_prompt: str = _STYLE,
    ) -> dict[str, Any]:
        quality = str(quality or "medium").lower()
        if quality not in _QUALITIES:
            raise ValueError("quality must be low, medium or high")
        if str(model or _MODEL) != _MODEL:
            raise ValueError("the grid run uses gpt-image-2")
        style_prompt = str(style_prompt or _STYLE).strip() or _STYLE
        if not style_prompt.isascii():
            raise ValueError("the style prompt must be plain ASCII")
        job = self._job_dir(name)
        grid_path = job / "grid.json"
        if not grid_path.is_file() or not (job / "plan.csv").is_file():
            raise ValueError("lay the grid first")
        grid = json.loads(grid_path.read_text(encoding="utf-8"))
        canvas = grid["canvas"]
        world = job / "scale" / "background_snapped.png"
        if not world.is_file():
            raise ValueError("snap the scaled map first")
        config: dict[str, Any] = {
            "world_map": str(world),
            "level_plan": str(job / "plan.csv"),
            "output_root": str(job),
            "canvas": {
                "mode": "explicit",
                "width": int(canvas[0]),
                "height": int(canvas[1]),
                "placement": "center",
                "margin": 0,
            },
            "scale": {"pixels_per_world_pixel": 1},
            "rendering": {
                "outside_color": [0, 0, 0, 255],
                "source_resampling": "lanczos",
            },
            "execution": {
                "approval_mode": "manual",
                "stop_on_failure": True,
                "retry_limit": 2,
                "rescale_below_iou": 0.0,
            },
            "generation": {
                "provider": "openai",
                "api_key_env": "OPENAI_API_KEY",
                "model": _MODEL,
                "quality": quality,
                "timeout_seconds": 900,
                "renderer": "warp",
                "mask_edits": True,
                "single_image": True,
            },
            "style_prompt": style_prompt,
        }
        overlay = job / "plan_overlay.png"
        if overlay.is_file():
            config["review_overlay"] = str(overlay)
        config_path = job / "config.json"

        def work() -> str:
            config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
            prepare_run(load_config(config_path))
            return str(job / "run.json")

        return self.start(f"prepare {name}", work)

    def open_review(self, name: str) -> dict[str, Any]:
        job = self._job_dir(name)
        run_path = job / "run.json"
        if not run_path.is_file():
            raise ValueError("prepare the run first")
        run = json.loads(run_path.read_text(encoding="utf-8"))
        levels = sorted(run["levels"])
        if not levels:
            raise ValueError("the run has no levels")
        self.review = ReviewPage(job, levels)
        return {"root": str(job), "levels": levels, "url": "/review"}


def _query_value(query: dict[str, list[str]], key: str) -> str:
    return (query.get(key) or [""])[0]


def dispatch_studio(studio: Studio, method: str, parts: list[str], query: dict[str, list[str]], body: dict) -> Any:
    if method == "GET" and parts == ["status"]:
        return studio.status()
    if method == "GET" and parts == ["runs"]:
        return studio.list_runs()
    if method == "GET" and parts == ["worlds"]:
        return studio.list_worlds()
    if method == "GET" and parts == ["compose"]:
        return studio.compose_state(_query_value(query, "run"), _query_value(query, "level"))
    if method == "GET" and parts == ["job"]:
        return studio.job_state(_query_value(query, "name"))
    if method == "GET" and parts == ["img"]:
        return studio.image_for(query)
    if method != "POST":
        raise KeyError("/".join(parts))
    if studio.busy():
        raise Busy()
    action = parts[0] if parts else ""
    if action == "compose":
        player = body.get("player_px")
        return studio.compose(
            str(body.get("run") or ""),
            str(body.get("level") or ""),
            str(body.get("prompt") or ""),
            quality=str(body.get("quality") or "medium"),
            model=str(body.get("model") or _MODEL),
            player_px=None if player in (None, "", 0) else int(player),
        )
    if action == "accept":
        return studio.accept(str(body.get("run") or ""), str(body.get("level") or ""), int(body["attempt"]))
    if action == "scale":
        return studio.scale(
            str(body.get("run") or ""),
            str(body.get("level") or ""),
            str(body.get("name") or ""),
            width_tiles=int(body.get("width_tiles") or PRESET_TILES[0]),
            height_tiles=int(body.get("height_tiles") or PRESET_TILES[1]),
            tile_size=int(body.get("tile_size") or PRESET_TILES[2]),
        )
    if action == "snap":
        return studio.snap(str(body.get("name") or ""))
    if action == "grid":
        name = str(body.get("name") or "")

        def work() -> str:
            info = studio.write_grid(
                name,
                int(body.get("cols") or PRESET_GRID[0]),
                int(body.get("rows") or PRESET_GRID[1]),
                region=str(body.get("region") or ""),
                name_prefix=str(body.get("name_prefix") or "Level"),
                overlap_buffer=int(body.get("overlap_buffer") or DEFAULT_OVERLAP_BUFFER),
                crop_margin=int(body.get("crop_margin") or DEFAULT_CROP_MARGIN),
            )
            return f"{info['levels']} levels, canvas {info['canvas'][0]}x{info['canvas'][1]}"

        return studio.start(f"grid {name}", work)
    if action == "prepare":
        return studio.prepare(
            str(body.get("name") or ""),
            quality=str(body.get("quality") or "medium"),
            model=str(body.get("model") or _MODEL),
            style_prompt=str(body.get("style_prompt") or _STYLE),
        )
    if action == "review":
        return studio.open_review(str(body.get("name") or ""))
    raise KeyError(action)


class Busy(Exception):
    """A command is already running. The handler answers 409."""


def make_handler(studio: Studio) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send(self, status: int, body: bytes, content_type: str, cache: bool = False) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, status: int = HTTPStatus.OK) -> None:
            self._send(status, json.dumps(data).encode("utf-8"), "application/json")

        def _review_html(self) -> bytes:
            html = (WEB_DIR / "review.html").read_text(encoding="utf-8")
            html = html.replace(
                '<div id="top">',
                '<div id="top"><a href="/" style="color:#c9a227;margin-right:8px">Steps</a>',
                1,
            )
            return html.encode("utf-8")

        def _handle(self, method: str) -> None:
            url = urlparse(self.path)
            parts = [part for part in url.path.split("/") if part]
            if method == "GET" and not parts:
                page = WEB_DIR / "studio.html"
                self._send(HTTPStatus.OK, page.read_bytes(), "text/html; charset=utf-8")
                return
            if method == "GET" and parts == ["review"]:
                self._send(HTTPStatus.OK, self._review_html(), "text/html; charset=utf-8")
                return
            name = "/".join(parts)
            if method == "GET" and name in STATIC and name != "review.html":
                self._send(HTTPStatus.OK, (WEB_DIR / name).read_bytes(), STATIC[name])
                return
            if parts[:1] != ["api"]:
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            query = parse_qs(url.query)
            if parts[1:2] == ["studio"]:
                self._studio(method, parts[2:], query)
                return
            self._review(method, parts[1:], query)

        def _studio(self, method: str, parts: list[str], query: dict[str, list[str]]) -> None:
            if method == "POST" and studio.busy() and parts != ["status"]:
                self._json({"error": "A command is running."}, HTTPStatus.CONFLICT)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if method == "POST" else {}
                result = dispatch_studio(studio, method, parts, query, body)
            except Busy:
                self._json({"error": "A command is running."}, HTTPStatus.CONFLICT)
                return
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except KeyError as exc:
                self._json({"error": f"not found: {exc}"}, HTTPStatus.NOT_FOUND)
                return
            except Exception as exc:
                traceback.print_exc()
                self._json({"error": f"{type(exc).__name__}: {exc}"}, HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            if isinstance(result, Path):
                self._send(HTTPStatus.OK, result.read_bytes(), "image/png", cache=True)
            else:
                self._json(result)

        def _review(self, method: str, parts: list[str], query: dict[str, list[str]]) -> None:
            page = studio.review
            if parts == ["progress"]:
                self._json(page.run.snapshot() if page else {"running": False})
                return
            if studio.busy():
                self._json({"error": "A command is running."}, HTTPStatus.CONFLICT)
                return
            if page is None:
                self._json({"error": "no review is open"}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if method == "POST" else {}
                with page.lock:
                    result = dispatch(page, method, parts, query, body)
            except (ValueError, TypeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            except KeyError as exc:
                self._json({"error": f"not found: {exc}"}, HTTPStatus.NOT_FOUND)
                return
            except Exception as exc:
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


def serve(studio: Studio, port: int, open_browser: bool = True) -> None:
    try:
        server = _OwnPortServer(("127.0.0.1", port), make_handler(studio))
    except OSError:
        raise SystemExit(
            f"Port {port} is already in use by another program: start with --port and another number."
        )
    url = f"http://127.0.0.1:{port}/"
    print(f"Level studio: {url}   (Ctrl+C here to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
