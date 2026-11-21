"""Animation suite: the Kimodo clip library, mapping a clip onto a character, the map settings, rig versions.

    python -m tools.boss_sprite_pipeline.anim_web [--port 8768] [--no-browser]

Listens on 127.0.0.1 only. Data root: ANIM_DATA_ROOT, else OUTFIT_DATA_ROOT, else the Boss worktree
(rigging/paths.py). Characters are generated/bosses/characters/<id>/character.json (decisions) with rig
versions under rig/v<N>/; bakes write characters/<id>/bakes/<clip>/run.json. The clip index stays
generated/bosses/anim_library/index.json. See PLAN_rig_library.md.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tools.boss_sprite_pipeline.rigging import paths, sources
from tools.boss_sprite_pipeline.rigging.map import character as C
from tools.boss_sprite_pipeline.rigging.map.match import match
from tools.boss_sprite_pipeline.rigging.map.skeleton import load_bvh
from tools.boss_sprite_pipeline.rigging.rig import steps as RIG_STEPS
from tools.boss_sprite_pipeline.rigging.rig import version as V
from tools.boss_sprite_pipeline.rigging.rig.run_step import run_step
from tools.boss_sprite_pipeline.rigging.settings import SettingError, schema

PIPE = Path(__file__).resolve().parent
REPO = PIPE.parents[1]
WEB = PIPE / "web" / "anim.html"
NAME = __import__("re").compile(r"^[A-Za-z0-9_\-]+$")
LOG_KEEP = 400


def data_root() -> Path:
    return paths.data_root()


def generated() -> Path:
    return paths.generated()


def library() -> Path:
    return generated() / "bosses" / "anim_library"


def allowed_roots() -> list[Path]:
    return [
        (generated() / "bosses").resolve(),
        (generated() / "characters").resolve(),
        (generated() / "pod_sync").resolve(),
        (REPO / "Graphics" / "Meshes").resolve(),
    ]


def inside(path: Path) -> bool:
    try:
        p = path.resolve()
    except OSError:
        return False
    return any(p == r or r in p.parents for r in allowed_roots())


def resolve_rel(rel: str) -> Path:
    rel = rel.replace("\\", "/").lstrip("/")
    if not rel or rel.startswith("..") or "/../" in f"/{rel}/":
        raise ValueError("bad path")
    path = (generated() / rel).resolve()
    if not inside(path):
        raise ValueError("outside the data folders")
    return path


def bpy_python() -> Path:
    return paths.bpy_python()


def read_json(path: Path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1), encoding="utf-8")


def ensure_library() -> None:
    lib = library()
    lib.mkdir(parents=True, exist_ok=True)
    index = lib / "index.json"
    if index.is_file():
        return
    folder = generated() / "bosses" / "kimodo_new_blender"
    rows = []
    if folder.is_dir():
        for bvh in sorted(folder.glob("*.bvh")):
            rel = bvh.relative_to(generated()).as_posix()
            rows.append({"id": bvh.stem, "bvh": rel, "source": "soma", "prompt": None, "model": None,
                         "duration": None, "maps": {}})
    write_json(index, rows)


def load_index() -> list:
    return read_json(library() / "index.json", [])


def save_index(rows: list) -> None:
    write_json(library() / "index.json", rows)


def find_clip(clip_id: str) -> dict:
    for row in load_index():
        if row["id"] == clip_id:
            return row
    raise KeyError(clip_id)


def find_character(cid: str) -> dict:
    if not NAME.match(cid) or not C.exists(cid):
        raise KeyError(cid)
    return C.load(cid)


def clip_source(clip: dict) -> str:
    return clip.get("source") or "soma"


def bake_dir(cid: str, clip_id: str) -> Path:
    return paths.character_dir(cid) / "bakes" / clip_id


def characters_state() -> list:
    """Each character: its decisions, the resolved settings for a soma clip, its rig versions."""
    out = []
    for cid in C.all_ids():
        char = C.load(cid)
        row = {"id": cid, "template": char["template"], "rig": char["rig"], "map": char["map"],
               "view": paths.rel(paths.character_dir(cid) / "view" / f"v{char['rig']}"),
               "note": char.get("note", "")}
        try:
            row["settings"] = C.resolve(char, "soma")
        except SettingError as exc:
            row["settings_error"] = str(exc)
        vers = []
        for n in V.versions(cid):
            rec = V.load(cid, n)
            vers.append({"version": n, "step": rec["step"], "kind": rec["kind"], "input": rec["input"],
                         "accepted": rec["accepted"], "bone_hash": rec["bone_hash"], "when": rec["when"],
                         "note": rec.get("note", ""), "checks": rec.get("checks", {}),
                         "roles": sorted(rec["roles"])})
        row["versions"] = vers
        cur = next((v for v in vers if v["version"] == char["rig"]), None)
        row["bone_hash"] = cur["bone_hash"] if cur else None
        row["roles_hash"] = V.load(cid, char["rig"])["roles_hash"] if cur else None
        row["roles"] = cur["roles"] if cur else []
        out.append(row)
    return out


def rig_steps() -> list:
    return [{"name": m.NAME, "doc": m.DOC, "kind": m.KIND, "lane": m.LANE, "settings": schema(m.SETTINGS),
             "checks": {k: [list(r) for r in v] for k, v in m.CHECKS.items()}} for m in RIG_STEPS.STEPS.values()]


class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.lanes = {"local": None, "pod": None}
        self.done: list[dict] = []
        self.n = 0

    def snapshot(self) -> dict:
        with self.lock:
            run = []
            for j in self.lanes.values():
                if j:
                    run.append({"label": j["label"], "lane": j["lane"], "lines": j["lines"][-60:]})
            return {"running": run, "done": [{"label": j["label"], "lane": j["lane"], "rc": j["rc"],
                                               "lines": j["lines"][-40:]} for j in self.done[-20:]][::-1]}

    def start(self, lane: str, label: str, work) -> None:
        with self.lock:
            if self.lanes[lane]:
                raise RuntimeError(f"the {lane} lane is busy: {self.lanes[lane]['label']}")
            self.n += 1
            job = {"label": label, "lane": lane, "lines": [], "rc": None}
            self.lanes[lane] = job

        def run():
            rc = 1
            try:
                work(job["lines"])
                rc = 0
            except Exception as exc:
                job["lines"].append(str(exc))
                job["lines"].append(traceback.format_exc()[-1500:])
            with self.lock:
                job["rc"] = rc
                self.done.append(job)
                del self.done[:-20]
                self.lanes[lane] = None

        threading.Thread(target=run, daemon=True).start()


JOBS = Jobs()


def _log(lines, text: str) -> None:
    for line in text.splitlines():
        lines.append(line)
        del lines[:-LOG_KEEP]


def _run(cmd, lines, env=None, cwd=None) -> None:
    _log(lines, "$ " + " ".join(str(c) for c in cmd))
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(cmd, cwd=cwd, env=merged, capture_output=True, text=True)
    if proc.stdout:
        _log(lines, proc.stdout[-8000:])
    if proc.stderr:
        _log(lines, proc.stderr[-4000:])
    if proc.returncode != 0:
        raise RuntimeError(f"exit {proc.returncode}")


def run_map(clip_id: str, character_id: str, lines: list) -> dict:
    """Bake one clip onto the character's current rig version. Returns the index entry."""
    clip = find_clip(clip_id)
    char = find_character(character_id)
    n = int(char["rig"])
    rec = V.load(character_id, n)
    bvh = resolve_rel(clip["bvh"])
    if not bvh.is_file():
        raise FileNotFoundError(bvh)
    stage = library() / "stage" / character_id
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copy(bvh, stage / f"{clip_id}.bvh")
    out = bake_dir(character_id, clip_id)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    py = str(bpy_python())
    cmd = [py, str(PIPE / "retarget_bvh.py"), "--character", character_id, "--version", str(n),
           "--source", clip_source(clip), str(stage), str(out)]
    _run(cmd, lines, env={"ANIM_DATA_ROOT": str(data_root())}, cwd=str(PIPE))
    checks = ["pose check: " + line.split("POSE_CHECK", 1)[1].strip() for line in lines if "POSE_CHECK" in line]
    view = paths.character_dir(character_id) / "view" / f"v{n}"
    view.mkdir(parents=True, exist_ok=True)
    split = [py, str(PIPE / "viewer" / "export_split.py"), str(out / "animated.blend"), str(view)]
    if (view / "base.glb").is_file():
        split.append("--clips-only")
    _run(split, lines, cwd=str(PIPE))
    glb = view / "clips" / f"{clip_id}.glb"
    if not glb.is_file():
        raise FileNotFoundError(f"no {glb.name} in {view / 'clips'}")
    lines.extend(checks)      # last, so the page's job log ends on it
    return {"glb": paths.rel(glb), "rig": n, "bone_hash": rec["bone_hash"], "roles_hash": rec["roles_hash"],
            "bake": paths.rel(out / "run.json")}


def record_map(clip_id: str, character_id: str, entry) -> None:
    rows = load_index()
    for row in rows:
        if row["id"] == clip_id:
            row.setdefault("maps", {})[character_id] = entry
            break
    save_index(rows)


def bake_report(clip_id: str, cid: str) -> dict:
    """The last bake of this clip on this character: pose check, proportions, rig version, staleness."""
    char = find_character(cid)
    run = read_json(bake_dir(cid, clip_id) / "run.json", None)
    if run is None:
        return {"baked": False}
    clip = next(iter(run.get("clips", {}).values()), {})
    cur = V.load(cid, int(char["rig"]))
    rig = run.get("rig") or {}
    return {"baked": True, "rig": rig.get("version"), "current_rig": char["rig"],
            "stale": rig.get("bone_hash") != cur["bone_hash"] or rig.get("roles_hash") != cur["roles_hash"],
            "older_rig": rig.get("version") != char["rig"],
            "pose_check": clip.get("pose_check"), "proportions": clip.get("proportions"),
            "settings": run.get("settings"), "bind_flags": run.get("bind_flags"), "when": run.get("when")}


def match_report(clip_id: str, cid: str) -> dict:
    clip = find_clip(clip_id)
    char = find_character(cid)
    rec = V.load(cid, int(char["rig"]))
    sk = load_bvh(resolve_rel(clip["bvh"]).read_text(encoding="utf-8", errors="replace"))
    src = clip_source(clip)
    got = match(sources.label(sk.names, src), rec["roles"], [b["name"] for b in rec["bones"]],
                static=sources.get(src).STATIC)
    return {"paired": len(got["roles"]), "roles": got["roles"], "missing": got["missing"],
            "missing_required": got["missing_required"], "static": got["static"],
            "unmapped": got["unmapped"][:24], "rig": char["rig"], "source": src}


def execute_prompt(cell_path: Path, dest_dir: Path, host: str, port: str) -> None:
    """Copy one cell to the Kimodo pod, run serve_one.py --once, copy the BVH back.

    Tests replace this. The model name is inside the cell; serve_one.py defaults to RP-v1.
    """
    from tools.boss_sprite_pipeline.gpu_box.pod import MAIN_KEY, Pod
    pod = Pod(host, port, MAIN_KEY)
    name = cell_path.stem
    remote_in = f"/workspace/anim_in/{name}.json"
    pod.ssh("mkdir -p /workspace/anim_in /workspace/kimodo /workspace/runs")
    pod.put(PIPE / "kimodo" / "serve_one.py", "/workspace/kimodo/serve_one.py")
    pod.put(cell_path, remote_in)
    pod.ssh(f"python /workspace/kimodo/serve_one.py --once {remote_in}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    pod.get(f"/workspace/runs/{name}/", dest_dir)


def run_prompt(body: dict, lines: list, host: str, port: str) -> str:
    name = str(body.get("name") or "").strip()
    prompt = str(body.get("prompt") or "").strip()
    duration = str(body.get("duration") or "1.0 2.5 1.0").strip()
    if not NAME.match(name):
        raise ValueError("name must be letters, digits, underscore")
    if not prompt:
        raise ValueError("prompt is empty")
    cell = {"name": name, "prompt": prompt, "duration": duration, "seed": int(body.get("seed") or 12345),
            "samples": 1, "model": "Kimodo-SOMA-RP-v1"}
    cell_path = library() / "cells" / f"{name}.json"
    write_json(cell_path, cell)
    dest = library() / "pull" / name
    if dest.exists():
        shutil.rmtree(dest)
    _log(lines, f"cell {cell_path}")
    execute_prompt(cell_path, dest, host, port)
    found = list(dest.rglob("*.bvh"))
    if not found:
        raise FileNotFoundError("the pod returned no bvh")
    kept = library() / "bvh" / f"{name}.bvh"
    kept.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(found[0], kept)
    rel = kept.relative_to(generated()).as_posix()
    rows = [r for r in load_index() if r["id"] != name]
    rows.append({"id": name, "bvh": rel, "source": "soma", "prompt": prompt, "model": cell["model"],
                 "duration": duration, "maps": {}})
    rows.sort(key=lambda r: r["id"])
    save_index(rows)
    _log(lines, f"CELL_DONE {name}")
    return rel


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, ctype: str):
        if not path.is_file() or not inside(path):
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        arg = lambda k: q.get(k, [""])[0]
        try:
            if url.path in ("/", "/index.html"):
                data = WEB.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)
                return
            if url.path == "/api/state":
                return self._json({"clips": load_index(), "characters": characters_state(),
                                   "schema": schema(C.MAP_SETTINGS), "steps": rig_steps(), "jobs": JOBS.snapshot(),
                                   "root": str(data_root())})
            if url.path == "/api/match":
                return self._json(match_report(arg("clip"), arg("character")))
            if url.path == "/api/bake":
                return self._json(bake_report(arg("clip"), arg("character")))
            if url.path == "/bvh":
                clip = find_clip(arg("id"))
                return self._file(resolve_rel(clip["bvh"]), "application/octet-stream")
            if url.path == "/glb":
                return self._file(resolve_rel(arg("path")), "model/gltf-binary")
        except (KeyError, ValueError, FileNotFoundError, OSError) as exc:
            return self._json({"error": str(exc)}, 404)
        self.send_error(404)

    def do_POST(self):
        url = urlparse(self.path)
        body = self._body()
        try:
            if url.path == "/api/map":
                clip, cid = str(body.get("clip", "")), str(body.get("character", ""))
                if not NAME.match(clip) or not NAME.match(cid):
                    return self._json({"error": "bad clip or character"}, 400)
                find_clip(clip)
                find_character(cid)

                def work(lines, clip=clip, cid=cid):
                    entry = run_map(clip, cid, lines)
                    record_map(clip, cid, entry)
                    lines.append("MAP_DONE " + entry["glb"])

                JOBS.start("local", f"map {clip} → {cid}", work)
                return self._json({"started": True})
            if url.path == "/api/character":
                cid = str(body.get("character") or "")
                find_character(cid)
                char = C.set_map(cid, body.get("patch") or {})
                clip = body.get("clip")
                if clip:
                    if not NAME.match(str(clip)):
                        return self._json({"error": "bad clip"}, 400)

                    def work(lines, clip=clip, cid=cid):
                        entry = run_map(clip, cid, lines)
                        record_map(clip, cid, entry)
                        lines.append("MAP_DONE " + entry["glb"])

                    JOBS.start("local", f"rebake {clip} → {cid}", work)
                return self._json({"map": char["map"], "rebake": bool(clip)})
            if url.path == "/api/rig/run":
                cid, name = str(body.get("character") or ""), str(body.get("step") or "")
                char = find_character(cid)
                step = RIG_STEPS.get(name)
                inp = int(body.get("input") or char["rig"])
                V.load(cid, inp)

                def work(lines, cid=cid, name=name, inp=inp, settings=body.get("settings") or {}):
                    run_step(cid, name, settings, inp, lines)

                JOBS.start(step.LANE, f"rig {name} on {cid} v{inp}", work)
                return self._json({"started": True})
            if url.path == "/api/rig/use":
                cid = str(body.get("character") or "")
                find_character(cid)
                char = V.set_current(cid, int(body.get("version")))
                return self._json({"rig": char["rig"]})
            if url.path == "/api/prompt":
                host = str(body.get("host") or "")
                port = str(body.get("port") or "")
                if not host or not port:
                    return self._json({"error": "set the pod host and port first"}, 400)

                def work(lines, body=body, host=host, port=port):
                    run_prompt(body, lines, host, port)

                JOBS.start("pod", f"prompt {body.get('name')}", work)
                return self._json({"started": True})
        except RuntimeError as exc:
            return self._json({"error": str(exc)}, 400)
        except (KeyError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)
        self.send_error(404)


def make_server(port: int) -> ThreadingHTTPServer:
    ensure_library()
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Animation suite on 127.0.0.1")
    ap.add_argument("--port", type=int, default=8768)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    srv = make_server(args.port)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"anim suite  {url}   data {data_root()}", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
