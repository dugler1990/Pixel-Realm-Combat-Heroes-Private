"""Pieces shared by the local review pages. Only the entity page uses this now."""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

LOG_KEEP = 400
NAME = re.compile(r"^[A-Za-z0-9_\-]+$")
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".mp4": "video/mp4"}


def inside(path: Path, roots: list[Path]) -> bool:
    p = path.resolve()
    return any(p == r or r in p.parents for r in roots)


def read_clipboard() -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], capture_output=True, text=True,
                       timeout=20)
    return r.stdout.strip()


def check_key(name: str, value: str, keys: dict) -> None:
    """Reject a clipboard value that is not this key. Never include the value in the error."""
    _env, prefix = keys[name]
    others = [p for k, (_e, p) in keys.items() if p and k != name]
    if (prefix and not value.startswith(prefix)) or any(value.startswith(p) for p in others) \
            or len(value) < 20 or any(c.isspace() for c in value):
        raise ValueError(f"the clipboard does not hold a {name} key")


def save_upload(folder: Path, name: str, data_url: str) -> Path:
    name = re.sub(r"[^A-Za-z0-9_.\-]", "_", name or "attach.png")
    if not name.lower().endswith((".png", ".jpg")):
        raise ValueError("png or jpg only")
    dst = Path(folder) / f"{time.strftime('%Y%m%d_%H%M%S')}_{name}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(base64.b64decode(data_url.split(",", 1)[-1]))
    return dst


class Jobs:
    """Running commands and the last 20 finished ones. A job holds locks; a second job that wants
    a held lock is refused, so one session runs one command and only one game window opens."""

    def __init__(self, driver: list[str], cwd: Path):
        self.lock = threading.Lock()
        self.driver, self.cwd = driver, cwd
        self.running: list[dict] = []
        self.done: list[dict] = []
        self.n = 0

    def start(self, key: str, args: list[str], locks: set[str]) -> dict:
        with self.lock:
            held = {name for job in self.running for name in job["locks"]}
            if locks & held:
                raise ValueError(f"busy: {', '.join(sorted(locks & held))}")
            self.n += 1
            job = {"id": self.n, "key": key, "args": args, "locks": sorted(locks), "lines": [],
                   "label": " ".join(args), "started": time.time(), "rc": None}
            self.running.append(job)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def snapshot(self) -> dict:
        with self.lock:
            return {"running": [dict(j, lines=j["lines"][-60:]) for j in self.running],
                    "done": [dict(j, lines=j["lines"][-60:]) for j in self.done[-20:]][::-1]}

    def last(self, key: str) -> dict | None:
        """The running job for `key`, else its last finished one."""
        with self.lock:
            for job in self.running + self.done[::-1]:
                if job["key"] == key:
                    return dict(job, lines=list(job["lines"]))
        return None

    def _run(self, job: dict) -> None:
        try:
            p = subprocess.Popen([*self.driver, *job["args"]], cwd=self.cwd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                 env=dict(os.environ, PYTHONUNBUFFERED="1"))
            for line in p.stdout:
                with self.lock:
                    job["lines"].append(line.rstrip("\n"))
                    del job["lines"][:-LOG_KEEP]
            rc = p.wait()
        except Exception as exc:                       # the command could not start at all
            job["lines"].append(f"could not run: {exc}")
            rc = -1
        with self.lock:
            job["rc"], job["ended"] = rc, time.time()
            self.running.remove(job)
            self.done.append(job)
            del self.done[:-20]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):                      # quiet: the page polls every 2 s
        pass

    def send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def json(self, obj, code: int = 200) -> None:
        self.send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def send_file(self, path: Path, roots: list[Path]) -> None:
        ctype = TYPES.get(path.suffix.lower())
        if not ctype or not path.is_file() or not inside(path, roots):
            return self.send(404, b"not found", "text/plain")
        data = path.read_bytes()
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        if not m or not (m.group(1) or m.group(2)):
            return self.send(200, data, ctype)
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)) if m.group(2) else len(data) - 1, len(data) - 1)
        else:                                          # bytes=-N: the last N bytes
            start, end = max(0, len(data) - int(m.group(2))), len(data) - 1
        if start > end:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(data)}")
            self.end_headers()
            return
        self.send_response(206)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data[start:end + 1])
