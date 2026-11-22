"""The entity pipeline in the browser.

    python -m tools.entity_pipeline.web [--port 8769] [--no-browser]

Every button runs one CLI command. The page reads the session folder; it never writes session.json.
Listens on 127.0.0.1 only (8765 SAM, 8766 levels, 8767 outfits, 8768 anim, 8769 entity).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.entity_pipeline.frames import ACTIONS  # noqa: E402
from tools.entity_pipeline.session import WORK_ROOT  # noqa: E402
from tools.entity_pipeline.wire import roster_counts  # noqa: E402
from tools.review_web import (  # noqa: E402
    NAME,
    Handler,
    Jobs,
    check_key,
    inside,
    read_clipboard,
    save_upload,
)

WEB = Path(__file__).resolve().parent / "web" / "index.html"
WORK = (_ROOT / WORK_ROOT).resolve()
MONSTERS = (_ROOT / "Graphics" / "Monsters").resolve()
MEDIA_ROOTS = [WORK, MONSTERS]
MAP_ROOTS = [WORK, (_ROOT / "levels").resolve()]
KEYS = {"openai": ("OPENAI_API_KEY", "sk-"), "leonardo": ("LEONARDO_API_KEY", "")}
_IMAGE = {".png", ".jpg", ".jpeg"}


def status(output: Path, inputs: list[Path]) -> str:
    """missing: no output. stale: an input is missing or newer than the output. done: otherwise.
    A redraw writes a new file (newer); a rename (stats) keeps the time, so it stays done."""
    if not output.exists():
        return "missing"
    made = output.stat().st_mtime
    if any(not p.exists() or p.stat().st_mtime > made for p in inputs):
        return "stale"
    return "done"


def _fold(parts: list[str]) -> str:
    """All done → done. All missing (or no warriors) → missing. Any stale → stale. Else partial."""
    if not parts or all(part == "missing" for part in parts):
        return "missing"
    if all(part == "done" for part in parts):
        return "done"
    if any(part == "stale" for part in parts):
        return "stale"
    return "partial"


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _existing(path: Path) -> str | None:
    return str(path) if path.is_file() else None


def _cells(w: Path) -> list[str]:
    folder = w / "cells"
    if not folder.is_dir():
        return []
    return sorted(path.stem for path in folder.glob("*.png"))


def _map_input(data: dict) -> Path:
    raw = data.get("map_image")
    if not raw:
        return Path("__missing_map__")
    path = Path(str(raw))
    return path if path.is_absolute() else _ROOT / path


def _frame_inputs(w: Path, name: str) -> list[Path]:
    inputs = [w / "anim" / name / f"{action}.mp4" for action in ACTIONS]
    inputs.append(w / "layout.json")
    stats_path = w / "stats.json"
    if stats_path.exists():
        inputs.append(stats_path)
    return inputs


def _brawl_inputs(w: Path, names: list[str]) -> list[Path]:
    inputs = [MONSTERS / name / "_contact.png" for name in names]
    stats_path = w / "stats.json"
    if stats_path.exists():
        inputs.append(stats_path)
    return inputs


def _costs(data: dict) -> tuple[float, int]:
    cost, unknown = 0.0, 0
    for call in data.get("calls") or []:
        if not isinstance(call, dict):
            continue
        value = call.get("cost_usd")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            if value is None:
                unknown += 1
            continue
        cost += float(value)
    return cost, unknown


def step_status(w: Path) -> dict:
    data = _read_json(w / "session.json")
    names = _cells(w)
    anim, frames = [], []
    for name in names:
        cell = w / "cells" / f"{name}.png"
        for action in ACTIONS:
            anim.append(status(w / "anim" / name / f"{action}.mp4", [cell]))
        frames.append(status(MONSTERS / name / "_contact.png", _frame_inputs(w, name)))
    return {
        "scene": status(w / "scene.png", [_map_input(data)]),
        "sheet": status(w / "sheet.png", [w / "scene.png"]),
        "cut": status(w / "layout.json", [w / "sheet.png"]),
        "stats": status(w / "stats.json", [w / "layout.json"]),
        "anim": _fold(anim),
        "frames": _fold(frames),
        "brawl": status(w / "brawl.json", _brawl_inputs(w, names)),
    }


def sessions() -> list[dict]:
    if not WORK.is_dir():
        return []
    found = []
    for folder in sorted(path for path in WORK.iterdir() if path.is_dir()):
        data = _read_json(folder / "session.json")
        cost, unknown = _costs(data)
        found.append({
            "name": folder.name,
            "steps": step_status(folder),
            "cost_usd": cost,
            "calls_unknown": unknown,
        })
    return found


def session_detail(name: str) -> dict:
    w = WORK / name
    data = _read_json(w / "session.json")
    raw_scores = _read_json(w / "stats.json").get("scores")
    scores = raw_scores if isinstance(raw_scores, dict) else {}
    clean = {key: row for key, row in scores.items() if isinstance(row, dict)}
    counts = roster_counts(clean) if clean else {}
    warriors = []
    for n in _cells(w):
        cell = w / "cells" / f"{n}.png"
        anim = {}
        for action in ACTIONS:
            clip = w / "anim" / n / f"{action}.mp4"
            anim[action] = {
                "status": status(clip, [cell]),
                "path": str(clip) if clip.is_file() else None,
            }
        contact = MONSTERS / n / "_contact.png"
        warriors.append({
            "name": n,
            "cell": str(cell),
            "anim": anim,
            "frames": {
                "status": status(contact, _frame_inputs(w, n)),
                "contact": str(contact) if contact.is_file() else None,
            },
            "score": clean.get(n),
            "copies": counts.get(n),
        })
    return {
        "name": name,
        "map_image": data.get("map_image"),
        "band": data.get("band") or "near",
        "steps": step_status(w),
        "scene": _existing(w / "scene.png"),
        "sheet": _existing(w / "sheet.png"),
        "contact": _existing(w / "contact.png"),
        "brawl": _existing(w / "brawl.json"),
        "scene_prompt": _text(w / "scene_prompt.txt"),
        "sheet_prompt": _text(w / "sheet_prompt.txt"),
        "warriors": warriors,
    }


def _why(body: dict) -> str | None:
    if "why" not in body or body["why"] is None:
        return None
    text = str(body["why"]).strip()
    if len(text) > 500:
        raise ValueError("why is too long")
    if not text:
        raise ValueError("why is empty")
    return text


def _map_file(session: str, body: dict) -> Path:
    raw = body.get("map")
    folder = WORK / session
    if not raw:
        if not folder.is_dir():
            raise ValueError("a new session needs a map")
        raw = _read_json(folder / "session.json").get("map_image")
    if not raw:
        raise ValueError("map image required")
    path = Path(str(raw))
    path = path.resolve() if path.is_absolute() else (_ROOT / path).resolve()
    if path.suffix.lower() not in _IMAGE or not path.is_file() or not inside(path, MAP_ROOTS):
        raise ValueError("map must be a png or jpeg under the map folders")
    return path


def _attach(folder: Path, body: dict) -> str | None:
    if not body.get("attach"):
        return None
    path = Path(str(body["attach"])).resolve()
    if not path.is_file() or not inside(path, [(folder / "uploads").resolve()]):
        raise ValueError("attach must be a file in the session uploads")
    return str(path)


def _cell(folder: Path, name) -> str:
    if not isinstance(name, str) or not NAME.match(name) or not (folder / "cells" / f"{name}.png").is_file():
        raise ValueError("not a cell of this session")
    return name


def _number(body: dict, key: str, default, kind: str):
    value = body.get(key, default)
    if kind == "each":
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("each must be an integer >= 1")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError("hold must be a number > 0")
    return value


def build_argv(body: dict) -> tuple[str, list[str], set[str]]:
    """The CLI args for one button. Flags are added only when the body has them."""
    step = body.get("step")
    session = body.get("session") or ""
    if not isinstance(session, str) or not NAME.match(session):
        raise ValueError("bad session")
    folder = WORK / session
    locks = {f"session:{session}"}
    force = bool(body.get("force"))
    why = _why(body) if step in ("scene", "sheet", "anim") else None

    if step == "scene":
        args = ["scene", "--session", session, "--image", str(_map_file(session, body)), "--yes"]
    elif step == "sheet":
        args = ["sheet", "--session", session, "--yes"]
    elif step == "cut":
        args = ["cut", "--session", session, "--yes"]
    elif step == "stats":
        args = ["stats", "--session", session]
    elif step == "anim":
        name = _cell(folder, body.get("name"))
        action = body.get("action")
        if why and not action:
            raise ValueError("--why redraws one clip: add --action idle, move or attack")
        if action and action not in ACTIONS:
            raise ValueError("bad action")
        args = ["anim", "--session", session, "--name", name, "--yes"]
        if action:
            args += ["--action", action]
    elif step == "anim-all":
        args = ["anim-all", "--session", session, "--yes"]
    elif step == "frames":
        name = _cell(folder, body.get("name"))
        band = body.get("band")
        if band and band not in ("near", "center"):
            raise ValueError("bad band")
        args = ["frames", "--session", session, "--name", name, "--yes"]
        if band:
            args += ["--band", band]
    elif step == "brawl":
        each = _number(body, "each", 1, "each")
        hold = _number(body, "hold", 60, "hold")
        args = ["brawl", "--session", session, "--each", str(each), "--hold", str(hold), "--yes"]
        locks.add("game")
    else:
        raise ValueError(f"unknown step {step!r}")

    if force and step in ("scene", "sheet", "stats", "anim"):
        args.append("--force")
    if why:
        args += ["--why", why]
    if step in ("scene", "sheet"):
        attach = _attach(folder, body)
        if attach:
            args += ["--attach", attach]
    return session, args, locks


def make_handler(jobs: Jobs):
    class EntityHandler(Handler):
        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    if not WEB.is_file():
                        return self.send(404, b"not found", "text/plain")
                    return self.send(200, WEB.read_bytes(), "text/html; charset=utf-8")
                if u.path == "/api/state":
                    keys = {k: bool(os.environ.get(env)) for k, (env, _prefix) in KEYS.items()}
                    return self.json({"sessions": sessions(), "jobs": jobs.snapshot(), "keys": keys})
                if u.path == "/api/session":
                    name = q.get("name", "")
                    if not NAME.match(name) or not (WORK / name).is_dir():
                        return self.json({"error": "no such session"}, 404)
                    return self.json(session_detail(name))
                if u.path == "/api/log":
                    name = q.get("name", "")
                    if not NAME.match(name):
                        return self.json({})
                    return self.json(jobs.last(name) or {})
                if u.path == "/media":
                    return self.send_file(Path(q.get("path", "")), MEDIA_ROOTS)
                return self.send(404, b"not found", "text/plain")
            except (Exception, SystemExit) as exc:
                return self.json({"error": f"{type(exc).__name__}: {exc}"}, 500)

        def do_POST(self):
            u = urlparse(self.path)
            try:
                b = self.body()
                if u.path == "/api/do":
                    key, args, locks = build_argv(b)
                    job = jobs.start(key, args, locks)
                    return self.json({"started": job["id"]})
                if u.path == "/api/key":
                    name = b.get("name")
                    if name not in KEYS:
                        raise ValueError("unknown key")
                    value = read_clipboard()
                    check_key(name, value, KEYS)
                    os.environ[KEYS[name][0]] = value
                    return self.json({"set": True})
                if u.path == "/api/upload":
                    session = b.get("session") or ""
                    if not isinstance(session, str) or not NAME.match(session) or not (WORK / session).is_dir():
                        raise ValueError("no such session")
                    path = save_upload(WORK / session / "uploads", b.get("name") or "attach.png", b["data"])
                    return self.json({"path": str(path)})
                return self.json({"error": "not found"}, 404)
            except (ValueError, KeyError, SystemExit) as exc:
                return self.json({"error": str(exc)}, 400)
            except Exception as exc:
                return self.json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    return EntityHandler


def make_server(port: int, jobs: Jobs | None = None) -> ThreadingHTTPServer:
    if jobs is None:
        jobs = Jobs([sys.executable, "-m", "tools.entity_pipeline.cli"], _ROOT)
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(jobs))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8769)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    server = make_server(a.port)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"entity page: {url}  Ctrl+C stops it", flush=True)
    if not a.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
