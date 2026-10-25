"""Orchestrator: run a boss through concept → mesh → rig → animate → render → pack.

    python -m tools.boss_sprite_pipeline.pipeline tools/boss_sprite_pipeline/bosses/<boss>.json
        [--from STAGE] [--to STAGE] [--gpu-host user@host] [--remote-root PATH]

Stages are inclusive on both ends; each writes into ``<workdir>/<stage>/`` and
records itself in ``<workdir>/state.json`` so a re-run from any stage picks up
the previous outputs. Run from the repo root.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from . import animate, concept, mesh, pack_frames, rig
from .backends.gpu_exec import GpuExec

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
STAGES = ["concept", "mesh", "rig", "animate", "render", "pack"]


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    cfg.setdefault("workdir", f"generated/bosses/{cfg['name']}")
    cfg.setdefault("install_root", "Graphics/Monsters")
    return cfg


def load_state(workdir: Path) -> dict:
    p = workdir / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"stages": {}}


def save_state(workdir: Path, state: dict) -> None:
    (workdir / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def run_render(cfg: dict, workdir: Path, state: dict) -> Path:
    render_cfg = dict(cfg)
    render_cfg["source"] = cfg.get("source") or state.get("anim_source")
    if not render_cfg["source"]:
        raise SystemExit("render: no source — set `source` in the boss config or run the animate stage")
    cfg_path = workdir / "render_config.json"
    cfg_path.write_text(json.dumps(render_cfg, indent=2), encoding="utf-8")
    subprocess.run(
        [str(HERE / ".venv-bpy" / "bin" / "python"), str(HERE / "render_frames.py"), str(cfg_path), str(workdir)],
        check=True,
    )
    return workdir / "frames"


def run_pipeline(config_path: Path, *, start: str = "concept", stop: str = "pack",
                 gpu_host: str | None = None, remote_root: str | None = None) -> None:
    cfg = load_config(config_path)
    workdir = (REPO_ROOT / cfg["workdir"]).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    state = load_state(workdir)
    gpu = GpuExec(REPO_ROOT, gpu_host or cfg.get("gpu_host"), remote_root or cfg.get("remote_root"))

    todo = STAGES[STAGES.index(start): STAGES.index(stop) + 1]
    print(f"boss {cfg['name']}  workdir {workdir}  stages {todo}  gpu_host {gpu.gpu_host or 'local'}")
    for stage in todo:
        t0 = time.time()
        print(f"\n== {stage} ==", flush=True)
        if stage == "concept":
            out = concept.run(cfg, workdir, REPO_ROOT)
        elif stage == "mesh":
            out = mesh.run(cfg, workdir, gpu)
        elif stage == "rig":
            out = rig.run(cfg, workdir, gpu)
        elif stage == "animate":
            out = animate.run(cfg, workdir)
            state["anim_source"] = out.relative_to(workdir).as_posix()
        elif stage == "render":
            out = run_render(cfg, workdir, state)
        elif stage == "pack":
            out = pack_frames.pack(workdir, (REPO_ROOT / cfg["install_root"]).resolve(), name=cfg["name"],
                                   alpha_floor=int(cfg.get("pack", {}).get("alpha_floor", pack_frames.ALPHA_FLOOR)))
        state["stages"][stage] = {
            "output": str(out), "seconds": round(time.time() - t0, 1),
            "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
            "backend": (cfg.get("stages", {}).get(stage, {}) or {}).get("backend"),
        }
        save_state(workdir, state)
        print(f"   {stage} done in {time.time() - t0:.0f}s → {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", type=Path)
    ap.add_argument("--from", dest="start", choices=STAGES, default="concept")
    ap.add_argument("--to", dest="stop", choices=STAGES, default="pack")
    ap.add_argument("--gpu-host", default=None, help="user@host to run ML stages over ssh (default: local)")
    ap.add_argument("--remote-root", default=None, help="repo checkout path on the GPU box")
    args = ap.parse_args()
    if STAGES.index(args.start) > STAGES.index(args.stop):
        raise SystemExit("--from must not come after --to")
    run_pipeline(args.config.resolve(), start=args.start, stop=args.stop,
                 gpu_host=args.gpu_host, remote_root=args.remote_root)


if __name__ == "__main__":
    main()
