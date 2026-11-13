"""The outfit web page: the outfit pipeline (outfit.py) in the browser. Plan: .cursor/plans/outfit_web.plan.md.

    python -m tools.boss_sprite_pipeline.outfit_web [--port 8767] [--no-browser]

Every button runs one driver step, the same command a person would type:
    outfit.py <character> <outfit> --only <step> [--accept N | --retry R | --pick M | --redo V... | --view V]
in a background thread. run.json stays the only state: the page reads it, never writes it. Two lanes: pod steps
(trellis, sam3, holopart) and local steps, one command per lane and one per outfit at a time, so one outfit's
pod step runs while another waits at a drawing gate. Listens on 127.0.0.1 only (8765 SAM, 8766 levels).

Keys: read from the environment at launch; the page shows which are set, never a value. "From clipboard" reads
the clipboard once into this process's environment (PowerShell Get-Clipboard), checked by prefix, never echoed.
The pod: paste RunPod's ssh line; gpu_box/pod.py address finds the direct IP / port. The page never starts or
stops a pod; it shows "stop the pod" when no pod step runs.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tools.boss_sprite_pipeline import outfit as of

WEB = Path(__file__).resolve().parent / "web" / "outfit.html"
POD_PY = of.TOOLS / "gpu_box" / "pod.py"
KEYS = {"openai": ("OPENAI_API_KEY", "sk-"), "leonardo": ("LEONARDO_API_KEY", ""), "hf": ("HF_TOKEN", "hf_")}
LOG_KEEP = 400                                   # lines of a running command kept for the page
NAME = re.compile(r"^[A-Za-z0-9_\-]+$")


def data_root() -> Path:
    return Path(os.environ.get("OUTFIT_DATA_ROOT") or of.REPO)


def allowed_roots() -> list[Path]:
    return [(data_root() / "generated" / "bosses").resolve(), (of.REPO / "Graphics" / "Meshes").resolve()]


def inside(path: Path, roots: list[Path]) -> bool:
    p = path.resolve()
    return any(p == r or r in p.parents for r in roots)


class Jobs:
    """The running commands, one per lane; the finished ones kept for the page (last 20)."""

    def __init__(self, driver: list[str] | None = None):
        self.lock = threading.Lock()
        self.lanes: dict[str, dict | None] = {"pod": None, "local": None}
        self.done: list[dict] = []
        self.driver = driver or [sys.executable, "-m", "tools.boss_sprite_pipeline.outfit"]
        self.n = 0

    def snapshot(self) -> dict:
        with self.lock:
            run = [dict(j, proc=None, lines=j["lines"][-60:]) for j in self.lanes.values() if j]
            return {"running": run, "done": [dict(j, lines=j["lines"][-60:]) for j in self.done[-20:]][::-1]}

    def busy(self, key: str) -> bool:
        return any(j and j["outfit"] == key for j in self.lanes.values())

    def start(self, character: str, outfit: str, step: str | None, args: list[str], lane: str) -> dict:
        key = f"{character}/{outfit}"
        with self.lock:
            if self.lanes[lane]:
                raise ValueError(f"the {lane} lane is busy: {self.lanes[lane]['label']}")
            if self.busy(key):
                raise ValueError(f"{key} already has a command running")
            self.n += 1
            job = {"id": self.n, "outfit": key, "step": step, "lane": lane, "args": args, "lines": [],
                   "label": f"{key} {' '.join(args)}", "started": time.time(), "rc": None, "stopped": None,
                   "proc": None}
            self.lanes[lane] = job
        threading.Thread(target=self._run, args=(job, [*self.driver, character, outfit, *args]), daemon=True).start()
        return job

    def _run(self, job: dict, cmd: list[str]) -> None:
        try:
            p = subprocess.Popen(cmd, cwd=of.REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONUNBUFFERED="1"))
            job["proc"] = p
            for line in p.stdout:
                with self.lock:
                    job["lines"].append(line.rstrip("\n"))
                    del job["lines"][:-LOG_KEEP]
            job["rc"] = p.wait()
        except Exception as exc:                       # the command could not start at all
            job["lines"].append(f"could not run: {exc}")
            job["rc"] = -1
        text = "\n".join(job["lines"])
        if "STOPPED at" in text:
            job["stopped"] = text.split("STOPPED at", 1)[1].strip()
        job["ended"] = time.time()
        with self.lock:
            self.lanes[job["lane"]] = None
            job["proc"] = None
            self.done.append(job)
            del self.done[:-20]


class Pod:
    def __init__(self):
        self.host = os.environ.get("POD_HOST")
        self.port = os.environ.get("POD_PORT")
        self.status: dict | None = None
        self.status_at = 0.0
        self.lock = threading.Lock()

    def info(self) -> dict:
        return {"host": self.host, "port": self.port, "status": self.status,
                "status_age_s": round(time.time() - self.status_at) if self.status_at else None}

    def refresh(self) -> dict:
        if not (self.host and self.port):
            return self.info()
        with self.lock:
            if time.time() - self.status_at < 8:
                return self.info()
            r = subprocess.run([sys.executable, POD_PY, "status", "--host", self.host, "--port", self.port],
                               capture_output=True, text=True, timeout=60)
            hit = [l for l in r.stdout.splitlines() if l.startswith("POD_STATUS ")]
            self.status = json.loads(hit[-1][11:]) if hit else {"error": (r.stdout + r.stderr)[-300:]}
            self.status_at = time.time()
        return self.info()

    def address(self, line: str) -> dict:
        r = subprocess.run([sys.executable, POD_PY, "address", line], capture_output=True, text=True, timeout=120)
        hit = [l.split() for l in r.stdout.splitlines() if l.startswith("POD ")]
        if not hit:
            raise ValueError((r.stdout + r.stderr).strip()[-300:] or "no address")
        self.host, self.port = hit[-1][1], hit[-1][2]
        self.status, self.status_at = None, 0.0
        return self.info()


def outfits() -> list[dict]:
    rows = []
    for f in sorted((of.TOOLS / "outfits").glob("*/*.json")):
        ctx = of.Ctx(f.parent.name, f.stem)
        steps = of.STEPS[ctx.o["kind"]]
        rows.append({"character": ctx.character, "outfit": ctx.outfit, "kind": ctx.o["kind"],
                     "about": ctx.o.get("_about", ""), "models": ctx.models() if ctx.o["kind"] != "cut" else [],
                     "steps": [{"name": s, "status": ctx.step(s).get("status", "-"),
                                "cost_usd": ctx.step(s).get("cost_usd"), "pod_minutes": ctx.step(s).get("pod_minutes"),
                                "time": ctx.step(s).get("time")} for s in steps],
                     "next": next((s for s in steps if not ctx.done(s)), None)})
    return rows


def run_detail(character: str, outfit: str) -> dict:
    ctx = of.Ctx(character, outfit)
    gate_dir, out = ctx.work / "gate", {}
    for g in sorted(gate_dir.glob("gate_*.json")):
        d = json.loads(g.read_text(encoding="utf-8"))
        for t in d.get("attempts", []):
            sheet = Path(t["draw"]).with_name(Path(t["draw"]).stem + "_sheet.png")
            t["sheet"] = str(sheet) if sheet.is_file() else None
        out[g.stem[5:]] = {"status": d.get("status"), "accepted": d.get("accepted"), "attempts": d.get("attempts", [])}
    paint = sorted((ctx.work / "paint" / "result").glob("after_*.png"), key=lambda p: int(p.stem.split("_")[1]))
    trellis = {m: str(ctx.work / "trellis" / f"{m}_from_front.glb")
               for m in of.MODEL_VIEWS if (ctx.work / "trellis" / f"{m}_from_front.glb").is_file()}
    images = {"trellis_sheet": ctx.work / "trellis" / "TRELLIS_SHEET.png",
              "cut_sheet": ctx.work / "cut" / "PARTS_SHEET.png", "cut_front": ctx.work / "cut" / "parts_000.png",
              "cut_back": ctx.work / "cut" / "parts_180.png", "slots_sheet": ctx.work / "slots" / "SLOTS_SHEET.png"}
    worn = sorted((ctx.work / "worn").glob("POSE_COMPARE*.png"))
    if worn:
        images["worn"] = worn[0]
    logs = {p.stem: p.stat().st_mtime for p in (ctx.work / "logs").glob("*.log")}
    cutouts = {v: (str(p) if (p := gate_dir / (f"{v}.png" if v in ("front", "back") else f"side_{v}.png")).is_file() else None)
               for v in ["front", "back"] + of.SIDE_ORDER}
    return {"run": ctx.run, "kind": ctx.o["kind"], "models": ctx.models(), "views": ctx.views(), "cutouts": cutouts,
            "mirror_right": ctx.o.get("mirror_right", True), "mirror_of": of.MIRROR_OF,
            "all_models": list(of.MODEL_VIEWS), "model_views": of.MODEL_VIEWS, "gates": out,
            "paint": [str(p) for p in paint], "trellis": trellis, "logs": logs,
            "images": {k: str(v) for k, v in images.items() if Path(v).is_file()}}


def build_args(ctx: of.Ctx, body: dict, pod: Pod) -> tuple[str | None, list[str], str]:
    """The driver arguments for one button, checked against the driver's own flags. Returns (step, args, lane)."""
    action, step = body.get("action"), body.get("step")
    steps = of.STEPS[ctx.o["kind"]]
    if action == "models":
        models = [m for m in body.get("models", []) if m in of.MODEL_VIEWS]
        if not models:
            raise ValueError("tick at least one model")
        return None, ["--models", ",".join(models), "--status"], "local"
    if step not in steps:
        raise ValueError(f"{step!r} is not a step of a {ctx.o['kind']} outfit")
    args = ["--only", step]
    if body.get("view"):
        if body["view"] not in of.SIDE_ORDER:
            raise ValueError("unknown view")
        args += ["--view", body["view"]]
    if action == "run":
        pass
    elif action == "accept":
        args += ["--accept", str(int(body["n"]))]
    elif action == "retry":
        retry = str(body.get("retry") or "r").strip()
        if not re.match(r"^(r|r1|rb)(\s|$)", retry):
            raise ValueError("a retry starts with r, r1 or rb")
        for img in re.findall(r"@(\S+)", retry):
            if not inside(Path(img), allowed_roots()):
                raise ValueError(f"attached image outside the run folders: {img}")
        args += ["--retry", retry]
    elif action == "pick":
        if body.get("model") not in of.MODEL_VIEWS:
            raise ValueError("unknown model")
        args += ["--pick", body["model"]]
    elif action == "redo":
        views = [v for v in body.get("views", []) if NAME.match(v)]
        if not views:
            raise ValueError("tick at least one view to repaint")
        args += ["--redo", *views]
    else:
        raise ValueError(f"unknown action {action!r}")
    lane = "pod" if step in of.POD_STEPS else "local"
    if lane == "pod":
        if not (pod.host and pod.port):
            raise ValueError("a pod step: paste the pod's ssh line first")
        args += ["--host", pod.host, "--port", pod.port]
    return step, args, lane


def read_clipboard() -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], capture_output=True, text=True,
                       timeout=20)
    return r.stdout.strip()


def make_handler(jobs: Jobs, pod: Pod):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):                  # quiet: the page polls every 2 s
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

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    return self.send(200, WEB.read_bytes(), "text/html; charset=utf-8")
                if u.path == "/api/state":
                    keys = {k: bool(os.environ.get(env)) for k, (env, _) in KEYS.items()}
                    return self.json({"outfits": outfits(), "jobs": jobs.snapshot(), "pod": pod.info(), "keys": keys,
                                      "data_root": str(data_root())})
                if u.path == "/api/run":
                    return self.json(run_detail(q["character"], q["outfit"]))
                if u.path == "/api/pod/status":
                    return self.json(pod.refresh())
                if u.path == "/api/log":
                    ctx = of.Ctx(q["character"], q["outfit"])
                    if not NAME.match(q.get("step", "")):
                        return self.json({"error": "bad step"}, 400)
                    p = ctx.work / "logs" / f"{q['step']}.log"
                    text = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
                    return self.json({"lines": text.splitlines()[-300:]})
                if u.path == "/img":
                    p = Path(q.get("path", ""))
                    if not p.is_file() or not inside(p, allowed_roots()) or p.suffix.lower() not in (".png", ".jpg"):
                        return self.send(404, b"not found", "text/plain")
                    return self.send(200, p.read_bytes(), "image/png" if p.suffix.lower() == ".png" else "image/jpeg")
                return self.send(404, b"not found", "text/plain")
            except (Exception, SystemExit) as exc:   # Ctx exits on an unknown outfit
                return self.json({"error": f"{type(exc).__name__}: {exc}"}, 500)

        def do_POST(self):
            u = urlparse(self.path)
            try:
                b = self.body()
                if u.path == "/api/do":
                    ctx = of.Ctx(b["character"], b["outfit"])
                    step, args, lane = build_args(ctx, b, pod)
                    job = jobs.start(ctx.character, ctx.outfit, step, args, lane)
                    return self.json({"started": job["id"], "label": job["label"]})
                if u.path == "/api/pod":
                    if b.get("line"):
                        return self.json(pod.address(b["line"]))
                    host, port = str(b.get("host", "")), str(b.get("port", ""))
                    if not re.match(r"^[0-9.]+$", host) or not port.isdigit():
                        raise ValueError("host = IP, port = number")
                    pod.host, pod.port, pod.status, pod.status_at = host, port, None, 0.0
                    return self.json(pod.info())
                if u.path == "/api/key":
                    name = b.get("name")
                    if name not in KEYS:
                        raise ValueError("unknown key")
                    env, prefix = KEYS[name]
                    value = read_clipboard()
                    others = [p for k, (_, p) in KEYS.items() if p and k != name]
                    if (prefix and not value.startswith(prefix)) or any(value.startswith(p) for p in others) \
                            or len(value) < 20 or any(c.isspace() for c in value):
                        raise ValueError(f"the clipboard does not hold a {name} key")
                    os.environ[env] = value
                    return self.json({"set": True})
                if u.path == "/api/upload":
                    ctx = of.Ctx(b["character"], b["outfit"])
                    name = re.sub(r"[^A-Za-z0-9_.\-]", "_", b.get("name") or "attach.png")
                    if not name.lower().endswith((".png", ".jpg")):
                        raise ValueError("png or jpg only")
                    dst = ctx.work / "gate" / "uploads" / f"{time.strftime('%Y%m%d_%H%M%S')}_{name}"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(base64.b64decode(b["data"].split(",", 1)[-1]))
                    return self.json({"path": str(dst)})
                return self.json({"error": "not found"}, 404)
            except (ValueError, KeyError, SystemExit) as exc:
                return self.json({"error": str(exc)}, 400)
            except Exception as exc:
                return self.json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    return Handler


def make_server(port: int, jobs: Jobs | None = None, pod: Pod | None = None) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(jobs or Jobs(), pod or Pod()))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8767)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)
    server = make_server(a.port)
    url = f"http://127.0.0.1:{a.port}/"
    print(f"outfit page: {url}  (data: {data_root()})  Ctrl+C stops it", flush=True)
    if not a.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
