"""Animation suite: the Kimodo library, one-clip retarget, and the fit knobs.

    python -m tools.boss_sprite_pipeline.anim_web [--port 8768] [--no-browser]

Listens on 127.0.0.1 only. Data root: ANIM_DATA_ROOT, else OUTFIT_DATA_ROOT, else the Boss
worktree when this one has no generated/bosses. The page reads index.json and characters.json
and writes them; a bake's run.json is written by retarget_bvh.py, not by this page.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PIPE = Path(__file__).resolve().parent
REPO = PIPE.parents[1]
WEB = PIPE / "web" / "anim.html"
NAME = __import__("re").compile(r"^[A-Za-z0-9_\-]+$")
LOG_KEEP = 400

DEFAULT_CHARACTERS = [
    {"id": "barb", "recipe": "human", "target": "barb", "source": "anunaki",
     "rig": "bosses/barb/rigfix/barb_final_nb.glb",
     "roles": "bosses/barb/gear_test/barb_roles.json",
     "base": "bosses/barb/viewer/ik_test2/base.glb",
     "view": "bosses/barb/viewer/anim_suite",
     "arm_cap": 90, "bind_match": True,
     "note": "UniRig human. Arm cap 90."},
    {"id": "demon", "recipe": "creature", "target": "demon", "source": "soma",
     "rig": "bosses/demon/rig/jaw/rigged_jaw_hinge.glb",
     "roles": "bosses/demon/rig/jaw/bone_roles.json",
     "base": "bosses/demon/viewer/_base.glb",
     "view": "bosses/demon/viewer/anim_suite",
     "arm_cap": 35, "bind_match": False,
     "note": "Fused armpit, arm cap 35, digitigrade. The key neck is the skull."},
    {"id": "icewiz", "recipe": "human", "source": "anunaki",
     "rig": "pod_sync/20261116/out/unirig_icewiz/rigged.glb",
     "roles": "bosses/icewiz/rig/icewiz_roles.json",
     "base": None,
     "view": "bosses/icewiz/viewer/anim_suite",
     "note": "Positional retarget. Roles from anun_roles.py."},
]


def data_root() -> Path:
    for key in ("ANIM_DATA_ROOT", "OUTFIT_DATA_ROOT"):
        if os.environ.get(key):
            return Path(os.environ[key])
    if (REPO / "generated" / "bosses").is_dir():
        return REPO
    boss = REPO.parent / "Pixel-Realm-Combat-Heroes-Boss"
    if (boss / "generated" / "bosses").is_dir():
        return boss
    return REPO


def generated() -> Path:
    return data_root() / "generated"


def library() -> Path:
    return generated() / "bosses" / "anim_library"


def allowed_roots() -> list[Path]:
    return [
        (generated() / "bosses").resolve(),
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
    env = os.environ.get("ANIM_BPY")
    if env:
        return Path(env)
    here = PIPE / ".venv-bpy" / "Scripts" / "python.exe"
    boss = REPO.parent / "Pixel-Realm-Combat-Heroes-Boss" / "tools" / "boss_sprite_pipeline" / ".venv-bpy" / "Scripts" / "python.exe"
    for c in (here, boss):
        if c.is_file():
            return c
    raise FileNotFoundError("no .venv-bpy python (set ANIM_BPY)")


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
    chars = lib / "characters.json"
    if not chars.is_file():
        rows = []
        for row in DEFAULT_CHARACTERS:
            need = row.get("roles")
            if need and not (generated() / need).is_file():
                continue
            rows.append(row)
        write_json(chars, rows)
    else:
        rows = read_json(chars, [])
        defaults = {row["id"]: row for row in DEFAULT_CHARACTERS}
        changed = False
        for row in rows:
            src = defaults.get(row.get("id"))
            if not src:
                continue
            for key in ("rig", "arm_cap", "bind_match", "source"):
                if key in src and key not in row:
                    row[key] = src[key]
                    changed = True
        if changed:
            write_json(chars, rows)
    index = lib / "index.json"
    if index.is_file():
        return
    folder = generated() / "bosses" / "kimodo_new_blender"
    rows = []
    if folder.is_dir():
        for bvh in sorted(folder.glob("*.bvh")):
            rel = bvh.relative_to(generated()).as_posix()
            rows.append({"id": bvh.stem, "bvh": rel, "prompt": None, "model": None,
                         "duration": None, "maps": {}})
    write_json(index, rows)


def load_index() -> list:
    return read_json(library() / "index.json", [])


def load_characters() -> list:
    return read_json(library() / "characters.json", [])


def find_clip(clip_id: str) -> dict:
    for row in load_index():
        if row["id"] == clip_id:
            return row
    raise KeyError(clip_id)


def find_character(cid: str) -> dict:
    for row in load_characters():
        if row["id"] == cid:
            return row
    raise KeyError(cid)


def save_index(rows: list) -> None:
    write_json(library() / "index.json", rows)


def fit_path(cid: str) -> Path:
    return library() / "fits" / f"{cid}.json"


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


def run_map(clip_id: str, character_id: str, lines: list) -> str:
    """Retarget one BVH. Returns the glb path relative to generated/."""
    clip = find_clip(clip_id)
    char = find_character(character_id)
    bvh = resolve_rel(clip["bvh"])
    if not bvh.is_file():
        raise FileNotFoundError(bvh)
    stage = library() / "stage" / character_id
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copy(bvh, stage / f"{clip_id}.bvh")
    out = generated() / "bosses" / character_id / "anim_suite" / clip_id
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    py = str(bpy_python())
    script = str(PIPE / "retarget_bvh.py")
    env = {"SOURCE": char.get("source") or "soma"}
    human = char.get("recipe") == "human"
    env["ARM_ELEV_CAP"] = str(char.get("arm_cap", 90 if human else 35))
    # These clips do not start from a stand. Bind match off keeps the character in his
    # rest pose and only plays the change from frame 1, so the stick and the mesh are
    # different poses. On, his limbs point the way the source limbs point.
    bind = char["bind_match"] if "bind_match" in char else human
    env["BIND_MATCH"] = "1" if bind else "0"
    patch = read_json(fit_path(character_id), {})
    from tools.boss_sprite_pipeline.rigmap.fit import knob_env
    env.update(knob_env(patch))
    # The barb bake graded good (2026-11-15, anim_test/retarget_ik2) was IK with hips and neck
    # left out of bind match. Without these the page can only do plain rotation copy.
    if char.get("mode"):
        env["RETARGET_MODE"] = str(char["mode"])
    if char.get("ik_body") is not None:
        env["IK_BODY"] = str(float(char["ik_body"]))
    if char.get("bind_skip"):
        env["BIND_SKIP"] = ",".join(char["bind_skip"])
    # absolute paths: retarget's --target resolves the rig under its own repo, which is
    # this worktree, and the meshes live in the data root
    rig = resolve_rel(char["rig"])
    roles = resolve_rel(char["roles"])
    cmd = [py, script, str(rig), str(roles), str(stage), str(out)]
    _run(cmd, lines, env=env, cwd=str(PIPE))
    view = resolve_rel(char["view"])
    view.mkdir(parents=True, exist_ok=True)
    base = view / "base.glb"
    if not base.is_file() and char.get("base"):
        src_base = resolve_rel(char["base"])
        if src_base.is_file():
            shutil.copy(src_base, base)
            _log(lines, f"copied base {src_base.name}")
    blend = out / "animated.blend"
    split = [py, str(PIPE / "viewer" / "export_split.py"), str(blend), str(view)]
    if base.is_file():
        split.append("--clips-only")
    _run(split, lines, cwd=str(PIPE))
    glb = view / "clips" / f"{clip_id}.glb"
    if not glb.is_file():
        # the action name inside the blend is the bvh stem, which is the clip id
        found = list((view / "clips").glob("*.glb"))
        if len(found) == 1:
            glb = found[0]
        else:
            raise FileNotFoundError(f"no clip glb in {view / 'clips'}")
    return glb.relative_to(generated()).as_posix()


def record_map(clip_id: str, character_id: str, glb_rel: str) -> None:
    rows = load_index()
    for row in rows:
        if row["id"] == clip_id:
            row.setdefault("maps", {})[character_id] = glb_rel
            break
    save_index(rows)


def match_report(clip_id: str, character_id: str) -> dict:
    from tools.boss_sprite_pipeline.rigmap import label_bvh, label_roles, load_bvh, match
    from tools.boss_sprite_pipeline.rigmap.label import bone_names
    clip = find_clip(clip_id)
    char = find_character(character_id)
    text = resolve_rel(clip["bvh"]).read_text(encoding="utf-8", errors="replace")
    sk = load_bvh(text)
    src = label_bvh(sk.names, "soma")
    roles = json.loads(resolve_rel(char["roles"]).read_text(encoding="utf-8"))
    dst = label_roles(roles, char["recipe"])
    got = match(src, dst, bone_names(roles))
    return {"paired": len(got["roles"]), "roles": got["roles"], "missing": got["missing"],
            "unmapped": got["unmapped"][:24], "recipe": char["recipe"]}


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
    if any(c in name for c in "."):
        raise ValueError("no dots in the name")
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
    rows.append({"id": name, "bvh": rel, "prompt": prompt, "model": cell["model"],
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
                return self._json({"clips": load_index(), "characters": load_characters(),
                                   "jobs": JOBS.snapshot(), "root": str(data_root())})
            if url.path == "/api/match":
                return self._json(match_report(q.get("clip", [""])[0], q.get("character", [""])[0]))
            if url.path == "/api/fit":
                cid = q.get("character", [""])[0]
                return self._json(read_json(fit_path(cid), {}))
            if url.path == "/bvh":
                clip = find_clip(q.get("id", [""])[0])
                return self._file(resolve_rel(clip["bvh"]), "application/octet-stream")
            if url.path == "/glb":
                return self._file(resolve_rel(q.get("path", [""])[0]), "model/gltf-binary")
        except (KeyError, ValueError, FileNotFoundError, OSError) as exc:
            return self._json({"error": str(exc)}, 404)
        self.send_error(404)

    def do_POST(self):
        url = urlparse(self.path)
        body = self._body()
        try:
            if url.path == "/api/map":
                clip, cid = body.get("clip", ""), body.get("character", "")
                if not NAME.match(str(clip)) or not NAME.match(str(cid)):
                    return self._json({"error": "bad clip or character"}, 400)
                find_clip(clip)
                find_character(cid)

                def work(lines, clip=clip, cid=cid):
                    rel = run_map(clip, cid, lines)
                    record_map(clip, cid, rel)
                    lines.append("MAP_DONE " + rel)

                JOBS.start("local", f"map {clip} → {cid}", work)
                return self._json({"started": True})
            if url.path == "/api/fit":
                cid = str(body.get("character") or "")
                if not NAME.match(cid):
                    return self._json({"error": "bad character"}, 400)
                find_character(cid)
                patch = body.get("patch") or {}
                allowed = {"barrel_chest", "arm_cap", "bind_match", "limb_reach"}
                clean = {k: patch[k] for k in allowed if k in patch and patch[k] is not None}
                write_json(fit_path(cid), clean)
                clip = body.get("clip")
                if clip:
                    if not NAME.match(str(clip)):
                        return self._json({"error": "bad clip"}, 400)

                    def work(lines, clip=clip, cid=cid):
                        rel = run_map(clip, cid, lines)
                        record_map(clip, cid, rel)
                        lines.append("FIT_DONE " + rel)

                    JOBS.start("local", f"fit {cid} {clip}", work)
                return self._json({"saved": clean, "rebake": bool(clip)})
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
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return srv


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
